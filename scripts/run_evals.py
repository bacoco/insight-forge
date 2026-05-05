#!/usr/bin/env python3
"""
Insight Forge — eval harness.

Runs the pipeline against each fixture under evals/fixtures/, compares the
resulting .insight-forge/ state to evals/expected/<name>.expected.yaml, and
emits a metrics report.

The single most important metric is `false_promotion_rate` — anything > 0
is a regression for the conservative-by-default contract.

USAGE:
    python3 scripts/run_evals.py
    python3 scripts/run_evals.py --fixture simple_success
    python3 scripts/run_evals.py --json   # machine-readable summary on stdout
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
EXPECTED_DIR = REPO_ROOT / "evals" / "expected"
PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "pipeline.py"

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# YAML helpers (pyyaml when available, fallback to pipeline's yaml_load_simple)
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        try:
            return _yaml.safe_load(text) or {}
        except Exception:
            pass
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from pipeline import yaml_load_simple  # noqa: E402
    return yaml_load_simple(text) or {}


# ---------------------------------------------------------------------------
# Pipeline runner — fresh forge dir per fixture, no contamination across runs
# ---------------------------------------------------------------------------

def run_pipeline_on_fixture(fixture: Path, rules_path: Path = None) -> Path:
    forge_dir = Path(tempfile.mkdtemp(prefix=f"forge-eval-{fixture.stem}-"))
    cmd = [sys.executable, str(PIPELINE_SCRIPT),
           "--input", str(fixture),
           "--forge-dir", str(forge_dir)]
    env = os.environ.copy()
    if rules_path:
        env["INSIGHT_FORGE_RULES_PATH"] = str(rules_path)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"pipeline.py failed on {fixture.name} (exit {result.returncode})")
    return forge_dir


# ---------------------------------------------------------------------------
# Observation: count crystallized entries by layer
# ---------------------------------------------------------------------------

def count_crystallized(forge_dir: Path) -> dict:
    """Count headings (## XNN: …) per logic file, plus staged-only count."""
    layers = {
        "heuristic": forge_dir / "logic" / "heuristics.md",
        "claim": forge_dir / "logic" / "claims.md",
        "dead_end": forge_dir / "logic" / "dead_ends.md",
        "constraint": forge_dir / "logic" / "constraints.md",
        "concept": forge_dir / "logic" / "concepts.md",
    }
    counts = {}
    total = 0
    for name, path in layers.items():
        n = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                # Heading like "## H01: title" / "## C02: …"
                if line.startswith("## ") and len(line.split()) >= 2:
                    head = line.split()[1].rstrip(":")
                    if head and head[0].isalpha() and head[1:].isdigit():
                        n += 1
        counts[name] = n
        total += n

    obs_data = load_yaml(forge_dir / "staging" / "observations.yaml") if (
        forge_dir / "staging" / "observations.yaml").exists() else {}
    observations = obs_data.get("observations", []) or []
    staged_only = sum(1 for o in observations if not o.get("promoted"))

    return {"total": total, "by_layer": counts, "staged_only": staged_only,
            "observations": observations}


def collect_signals(forge_dir: Path) -> list[str]:
    """Read every evidence bundle and return the list of crystallized_via values."""
    bundles_dir = forge_dir / "evidence" / "bundles"
    signals = []
    if not bundles_dir.exists():
        return signals
    for f in sorted(bundles_dir.glob("*.yaml")):
        if f.name.lower() == "readme.yaml":
            continue
        try:
            data = load_yaml(f)
            sig = data.get("crystallized_via")
            if sig:
                signals.append(sig)
        except Exception:
            pass
    return signals


def has_evidence_bundles(forge_dir: Path) -> bool:
    bundles_dir = forge_dir / "evidence" / "bundles"
    if not bundles_dir.exists():
        return False
    return any(f.name != "README.md" and f.suffix == ".yaml"
               for f in bundles_dir.iterdir())


def all_have_counter_evidence(forge_dir: Path) -> bool:
    bundles_dir = forge_dir / "evidence" / "bundles"
    if not bundles_dir.exists():
        return False
    found = False
    for f in sorted(bundles_dir.glob("*.yaml")):
        try:
            data = load_yaml(f)
            ce = (data.get("counter_evidence") or {}).get("text", "")
            if not ce or ce == "not_explored":
                return False
            found = True
        except Exception:
            return False
    return found


# ---------------------------------------------------------------------------
# Comparison + metrics
# ---------------------------------------------------------------------------

def compare(fixture_name: str, expected: dict, actual: dict,
            actual_signals: list[str], has_bundles: bool,
            counter_ok: bool) -> dict:
    """Return per-fixture diff: pass/fail + breakdown."""
    diffs = []

    exp_total = (expected.get("crystallized") or {}).get("total", 0)
    act_total = actual["total"]
    if exp_total != act_total:
        diffs.append(f"crystallized total: expected {exp_total}, got {act_total}")

    exp_layers = (expected.get("crystallized") or {}).get("by_layer", {}) or {}
    for layer, exp_n in exp_layers.items():
        got = actual["by_layer"].get(layer, 0)
        if got != exp_n:
            diffs.append(f"{layer}: expected {exp_n}, got {got}")

    exp_staged = expected.get("staged_only", 0)
    if exp_staged != actual["staged_only"]:
        diffs.append(f"staged_only: expected {exp_staged}, got {actual['staged_only']}")

    exp_signals = set(expected.get("expected_signals") or [])
    act_signals = set(actual_signals)
    if exp_signals and exp_signals != act_signals:
        diffs.append(f"signals: expected {sorted(exp_signals)}, got {sorted(act_signals)}")

    if expected.get("must_have_evidence_bundle") and not has_bundles:
        diffs.append("evidence bundle missing")
    if expected.get("must_have_counter_evidence") and not counter_ok:
        diffs.append("counter_evidence missing or 'not_explored'")

    return {
        "fixture": fixture_name,
        "passed": not diffs,
        "diffs": diffs,
        "expected_total": exp_total,
        "actual_total": act_total,
        "actual_signals": actual_signals,
    }


def aggregate_metrics(results: list[dict], expecteds: list[dict]) -> dict:
    """Compute the headline metrics across all fixtures."""
    n = len(results)
    if n == 0:
        return {}

    # false_promotion_rate: fraction of fixtures where actual > expected
    false_promotions = sum(1 for r in results if r["actual_total"] > r["expected_total"])
    # missed_promotions: actual < expected
    missed = sum(1 for r in results if r["actual_total"] < r["expected_total"])

    # provenance_coverage: fraction of fixtures with non-empty bundles when bundles
    # were expected; if not expected, contributes nothing.
    bundle_expected = [e for e in expecteds if e.get("must_have_evidence_bundle")]
    bundle_ok = 0
    for r, e in zip(results, expecteds):
        if e.get("must_have_evidence_bundle") and "evidence bundle missing" not in r["diffs"]:
            bundle_ok += 1
    provenance_coverage = (bundle_ok / len(bundle_expected)) if bundle_expected else 1.0

    return {
        "fixtures_run": n,
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "false_promotion_rate": false_promotions / n,
        "missed_promotion_rate": missed / n,
        "provenance_coverage": round(provenance_coverage, 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def verify_rule_contracts() -> int:
    """Check each rule's must_fire_on / must_not_fire_on claims against fixtures.

    Loads harness/rules.yaml, runs every fixture through the rule engine, and
    asserts that each rule's contract holds. Returns the number of contract
    violations (0 = clean).
    """
    sys.path.insert(0, str(REPO_ROOT))
    from harness.loader import load_rules, classify_with_rules  # noqa: E402

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from pipeline import CandidateEvent  # noqa: E402

    ruleset = load_rules()
    violations = 0

    # Build {fixture_stem: [CandidateEvent, ...]} once.
    fixture_events: dict[str, list] = {}
    for fixture in sorted(FIXTURES_DIR.glob("*.jsonl")):
        events = []
        for line in fixture.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("_marker"):
                continue
            events.append(CandidateEvent(
                session_id=obj.get("session_id", ""),
                session_short=obj.get("session_short", ""),
                agent=obj.get("agent", ""),
                timestamp=obj.get("timestamp", ""),
                role=obj.get("role", ""),
                content=obj.get("content", ""),
                tool_name=obj.get("tool_name"),
                tool_status=obj.get("tool_status"),
            ))
        fixture_events[fixture.stem] = events

    print("[contracts] verifying rule.contract.must_fire_on / must_not_fire_on")
    for rule in ruleset.rules:
        contract = rule.contract or {}
        must_fire = contract.get("must_fire_on", []) or []
        must_not_fire = contract.get("must_not_fire_on", []) or []

        for fixture_stem in must_fire:
            events = fixture_events.get(fixture_stem, [])
            fired = any(_rule_fires(rule, ev, ruleset) for ev in events)
            if not fired:
                print(f"  ✗ {rule.id}: must_fire_on={fixture_stem} but no event matched")
                violations += 1
            else:
                print(f"  ✓ {rule.id}: fires on {fixture_stem}")

        for fixture_stem in must_not_fire:
            events = fixture_events.get(fixture_stem, [])
            fired = any(_rule_fires(rule, ev, ruleset) for ev in events)
            if fired:
                print(f"  ✗ {rule.id}: must_not_fire_on={fixture_stem} but matched an event")
                violations += 1
            else:
                print(f"  ✓ {rule.id}: silent on {fixture_stem}")

    print()
    if violations:
        print(f"  {violations} contract violation(s)")
    else:
        print("  all rule contracts hold")
    return violations


def _rule_fires(rule, ev, ruleset) -> bool:
    """Check whether a single rule fires on a single event (without priority)."""
    from harness.loader import _matches  # noqa: E402
    if not _matches(rule.when, ev, ruleset):
        return False
    if rule.unless and _matches(rule.unless, ev, ruleset):
        return False
    return True


def main():
    p = argparse.ArgumentParser(description="Run insight-forge regression evals.")
    p.add_argument("--fixture", default=None,
                   help="Run a single fixture by stem name (e.g. simple_success).")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON on stdout.")
    p.add_argument("--keep-tmp", action="store_true",
                   help="Don't delete the temporary forge directories on exit.")
    p.add_argument("--verify-contracts", action="store_true",
                   help="Verify each rule's must_fire_on/must_not_fire_on contracts.")
    p.add_argument("--rules-path", default=None,
                   help="Override harness/rules.yaml — used by the proposer to "
                        "evaluate candidate edits in a sandbox.")
    p.add_argument("--include-gaps", action="store_true",
                   help="Include known-gap fixtures in the regression count "
                        "(default: skip them; gaps are exercised by propose_rules.py).")
    args = p.parse_args()

    if args.verify_contracts:
        sys.exit(0 if verify_rule_contracts() == 0 else 1)

    rules_path = Path(args.rules_path) if args.rules_path else None

    fixtures = sorted(FIXTURES_DIR.glob("*.jsonl"))
    if args.fixture:
        fixtures = [f for f in fixtures if f.stem == args.fixture]
        if not fixtures:
            sys.exit(f"Fixture not found: {args.fixture}")

    results = []
    expecteds = []
    tmp_dirs = []
    gap_results = []
    for fixture in fixtures:
        expected_path = EXPECTED_DIR / f"{fixture.stem}.expected.yaml"
        if not expected_path.exists():
            sys.stderr.write(f"[evals] No expected for {fixture.name} — skipping\n")
            continue
        expected = load_yaml(expected_path)
        forge_dir = run_pipeline_on_fixture(fixture, rules_path=rules_path)
        tmp_dirs.append(forge_dir)
        actual = count_crystallized(forge_dir)
        actual_signals = collect_signals(forge_dir)
        has_bundles = has_evidence_bundles(forge_dir)
        counter_ok = all_have_counter_evidence(forge_dir)
        result = compare(fixture.stem, expected, actual, actual_signals,
                          has_bundles, counter_ok)
        # Known gaps are tracked separately so the proposer can target them
        # without flipping main red.
        if expected.get("known_gap") and not args.include_gaps:
            result["gap"] = True
            gap_results.append(result)
            continue
        results.append(result)
        expecteds.append(expected)

    metrics = aggregate_metrics(results, expecteds)
    summary = {"results": results, "metrics": metrics, "gaps": gap_results}

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"  [{mark}] {r['fixture']:<32} signals={r['actual_signals']}")
            for d in r["diffs"]:
                print(f"         · {d}")
        for r in gap_results:
            mark = "GAP " if not r["passed"] else "GAP*"  # GAP* = unexpectedly passing
            print(f"  [{mark}] {r['fixture']:<32} signals={r['actual_signals']}")
            for d in r["diffs"]:
                print(f"         · {d}")
        print()
        print(f"  fixtures: {metrics.get('passed', 0)}/{metrics.get('fixtures_run', 0)} passed"
              + (f"  ({len(gap_results)} known gap{'s' if len(gap_results) != 1 else ''})"
                 if gap_results else ""))
        print(f"  false_promotion_rate:  {metrics.get('false_promotion_rate', 0):.2%}")
        print(f"  missed_promotion_rate: {metrics.get('missed_promotion_rate', 0):.2%}")
        print(f"  provenance_coverage:   {metrics.get('provenance_coverage', 0):.2%}")

    if not args.keep_tmp:
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    sys.exit(0 if metrics.get("failed", 0) == 0 else 1)


if __name__ == "__main__":
    main()
