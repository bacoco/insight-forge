#!/usr/bin/env python3
"""
Insight Forge — eval-graded rule proposer (Stanford Meta-Harness, baseline).

Closes the loop the two papers point at:

  rules.yaml (Tsinghua: harness as data)
  + evals/expected/*.yaml (Stanford: explicit contracts)
  + this script (proposer that edits the spec, graded by eval delta)

Workflow:
  1. Run regression evals against current rules.yaml.
  2. For every fixture marked `known_gap: true` that fails, identify its
     `target_rule` and generate a small candidate space of mutations:
       - regex_alternation_extend(rule, candidate_phrase)
         (extracts 1-3 leading tokens from each user/assistant message in the
          gap fixture and tries each as a new alternation branch)
  3. For each candidate, write a sandboxed rules.yaml to /tmp, run all
     fixtures (gaps included) against it, and score:
       - +N for each gap fixture now passing
       - -∞ for any contract violation (must_fire_on / must_not_fire_on)
       - -∞ for any regression on a previously-passing fixture
  4. Pick the highest-scoring candidate that has zero regressions and zero
     contract violations, write a proposal YAML to harness/proposals/<ts>.yaml.
  5. Never edit rules.yaml directly. The user reviews the proposal and applies
     it manually — same contract as propose_claude_md.py.

This v1 proposer is deterministic. The mutation generator is the swappable
seam; an LLM-based generator can replace it later without changing the
sandboxing or scoring code.

USAGE:
    python3 scripts/propose_rules.py
    python3 scripts/propose_rules.py --target-fixture french_heuristic
    python3 scripts/propose_rules.py --dry-run    # don't write the proposal file
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "harness" / "rules.yaml"
FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
EXPECTED_DIR = REPO_ROOT / "evals" / "expected"
PROPOSALS_DIR = REPO_ROOT / "harness" / "proposals"
RUN_EVALS = REPO_ROOT / "scripts" / "run_evals.py"

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        return _yaml.safe_load(text) or {}
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from pipeline import yaml_load_simple  # noqa: E402
    return yaml_load_simple(text) or {}


def dump_yaml(data: dict) -> str:
    if _HAS_YAML:
        return _yaml.safe_dump(data, allow_unicode=True, default_flow_style=False,
                                sort_keys=False)
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from pipeline import yaml_dump_simple  # noqa: E402
    return yaml_dump_simple(data) + "\n"


# ---------------------------------------------------------------------------
# Eval harness driver — run run_evals.py --json with a sandboxed rules.yaml
# ---------------------------------------------------------------------------

def run_evals(rules_path: Path = None, include_gaps: bool = True) -> dict:
    cmd = [sys.executable, str(RUN_EVALS), "--json"]
    if rules_path:
        cmd += ["--rules-path", str(rules_path)]
    if include_gaps:
        cmd.append("--include-gaps")
    res = subprocess.run(cmd, capture_output=True, text=True)
    # run_evals exits 1 on any failure; we still want the JSON
    if not res.stdout.strip():
        sys.stderr.write(res.stderr)
        raise SystemExit("run_evals.py produced no JSON")
    return json.loads(res.stdout)


def verify_contracts(rules_path: Path) -> int:
    """Return the count of contract violations against the given rules.yaml."""
    cmd = [sys.executable, str(RUN_EVALS), "--verify-contracts",
           "--rules-path", str(rules_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    # The script prints "✗" for each violation; count them.
    return res.stdout.count("✗ ")


# ---------------------------------------------------------------------------
# Candidate phrase extraction
# ---------------------------------------------------------------------------

# Strip stop-tokens that would never make a useful regex alternation. We keep
# this small and conservative — the eval harness will reject bad candidates,
# but trimming the search space saves wall-clock time.
_STOPWORDS = {
    "i", "you", "he", "she", "it", "we", "they",
    "a", "an", "the", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "at", "for", "with", "by",
    "and", "or", "but", "if", "as", "so", "do", "does",
    "le", "la", "les", "un", "une", "des", "du", "de",
    "et", "ou", "mais", "si", "que", "qui", "ce", "cette",
}


def extract_candidate_phrases(fixture_text: str, max_token_len: int = 3) -> list[str]:
    """Pull leading 1..max_token_len token phrases from each event content.

    The intuition: a missing rule alternation is almost always 1-3 tokens at
    the start of the message that the existing regex doesn't anchor on.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for line in fixture_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("_marker"):
            continue
        if obj.get("role") not in ("user", "assistant"):
            continue
        content = (obj.get("content") or "").strip()
        if not content:
            continue
        tokens = re.findall(r"[A-Za-zÀ-ÿ']+", content)
        for n in range(1, max_token_len + 1):
            if len(tokens) < n:
                break
            phrase = " ".join(tokens[:n]).lower()
            if phrase in seen:
                continue
            # Skip phrases that are pure stopwords (keep "il faut" though,
            # because "faut" is not a stopword)
            if all(t in _STOPWORDS for t in phrase.split()):
                continue
            seen.add(phrase)
            candidates.append(phrase)
    return candidates


# ---------------------------------------------------------------------------
# Mutation operators
# ---------------------------------------------------------------------------

def mutation_regex_alternation_extend(rule: dict, candidate: str) -> dict:
    """Append `candidate` to the first parenthesized alternation in the rule's
    `content_starts_with_regex` or `content_matches_regex` predicate.

    Returns a NEW rule dict (deep-copied at the levels we touch). Returns None
    if the rule has no extendable alternation.
    """
    new_rule = json.loads(json.dumps(rule))  # cheap deep copy
    when = new_rule.get("when") or {}
    for key in ("content_starts_with_regex", "content_matches_regex"):
        pattern = when.get(key)
        if not pattern:
            continue
        # Find the first parenthesized group with at least one '|'
        m = re.search(r"\(([^()]*\|[^()]*)\)", pattern)
        if not m:
            continue
        inner = m.group(1)
        # Skip if the candidate is already present (case-insensitive)
        existing = {p.strip().lower() for p in inner.split("|")}
        if candidate.strip().lower() in existing:
            return None
        new_inner = f"{inner}|{re.escape(candidate)}"
        new_pattern = pattern[:m.start(1)] + new_inner + pattern[m.end(1):]
        when[key] = new_pattern
        new_rule["when"] = when
        return new_rule
    return None


# ---------------------------------------------------------------------------
# Sandbox: write a candidate rules.yaml + run evals
# ---------------------------------------------------------------------------

def make_candidate_rules(base_rules: dict, target_rule_id: str,
                          mutated_rule: dict) -> dict:
    """Return a new rules dict with the target rule replaced by mutated_rule."""
    new_rules = json.loads(json.dumps(base_rules))
    for i, r in enumerate(new_rules.get("rules", [])):
        if r.get("id") == target_rule_id:
            new_rules["rules"][i] = mutated_rule
            return new_rules
    raise KeyError(f"No rule with id={target_rule_id}")


def score_candidate(rules_data: dict, baseline: dict, gap_fixtures: list[str]) -> dict:
    """Run evals against a candidate rules.yaml and return a score breakdown.

    Score: +1 per gap fixture that now passes; -∞ for ANY regression or
    contract violation.
    """
    tmp = Path(tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name)
    tmp.write_text(dump_yaml(rules_data), encoding="utf-8")
    try:
        violations = verify_contracts(tmp)
        if violations > 0:
            return {"score": float("-inf"), "reason": f"{violations} contract violation(s)",
                    "fixtures_fixed": [], "regressions": []}

        candidate_results = run_evals(rules_path=tmp, include_gaps=True)
        cand_by_name = {r["fixture"]: r for r in candidate_results.get("results", [])}
        base_by_name = {r["fixture"]: r for r in baseline.get("results", [])}

        regressions = []
        fixtures_fixed = []
        for name, base_r in base_by_name.items():
            cand_r = cand_by_name.get(name)
            if cand_r is None:
                continue
            if base_r["passed"] and not cand_r["passed"]:
                regressions.append(name)
            if not base_r["passed"] and cand_r["passed"]:
                fixtures_fixed.append(name)

        if regressions:
            return {"score": float("-inf"), "reason": f"regressions: {regressions}",
                    "fixtures_fixed": fixtures_fixed, "regressions": regressions}

        score = sum(1 for f in fixtures_fixed if f in gap_fixtures)
        return {"score": score, "reason": "ok",
                "fixtures_fixed": fixtures_fixed, "regressions": []}
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Proposal writer
# ---------------------------------------------------------------------------

def write_proposal(target_rule_id: str, gap_fixture: str,
                    base_rule: dict, mutated_rule: dict,
                    candidate_phrase: str, score_info: dict,
                    out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out = out_dir / f"{ts}-{target_rule_id}.yaml"
    proposal = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proposer": "deterministic-mutation-search-v1",
        "target_rule": target_rule_id,
        "gap_fixture": gap_fixture,
        "candidate_phrase": candidate_phrase,
        "metric_delta": {
            "fixtures_fixed": score_info["fixtures_fixed"],
            "regressions": score_info["regressions"],
            "score": score_info["score"],
        },
        "before": base_rule,
        "after": mutated_rule,
        "apply_instructions": (
            "Review `before` vs `after`. If accepted, replace the rule with the "
            "matching `id` in harness/rules.yaml with the `after` version, then "
            "remove `known_gap: true` from the gap fixture's expected.yaml so the "
            "regression evals start enforcing it."
        ),
    }
    out.write_text(dump_yaml(proposal), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=(
        "Eval-graded proposer for harness/rules.yaml. Generates mutations on rules "
        "targeted by known-gap fixtures, scores each by eval delta, and writes a "
        "reviewable proposal YAML — never edits rules.yaml directly."))
    p.add_argument("--target-fixture", default=None,
                   help="Restrict to one gap fixture by stem name (e.g. french_heuristic).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the proposal but don't write it to harness/proposals/.")
    p.add_argument("--max-candidates", type=int, default=20,
                   help="Cap on candidate phrases to evaluate per gap (default: 20).")
    args = p.parse_args()

    base_rules = load_yaml(RULES_PATH)
    baseline = run_evals(rules_path=None, include_gaps=True)

    # Find gap fixtures from expected files (cheaper than re-running)
    gap_fixtures: list[tuple[str, str, Path]] = []  # (fixture_stem, target_rule, fixture_path)
    for expected_path in sorted(EXPECTED_DIR.glob("*.expected.yaml")):
        exp = load_yaml(expected_path)
        if not exp.get("known_gap"):
            continue
        stem = expected_path.name.replace(".expected.yaml", "")
        target_rule = exp.get("target_rule")
        if not target_rule:
            print(f"[propose] {stem}: known_gap but no target_rule — skipping",
                  file=sys.stderr)
            continue
        if args.target_fixture and stem != args.target_fixture:
            continue
        gap_fixtures.append((stem, target_rule, FIXTURES_DIR / f"{stem}.jsonl"))

    if not gap_fixtures:
        print("[propose] No known-gap fixtures to optimize. rules.yaml is clean.")
        return

    proposals_written: list[Path] = []
    for stem, target_rule, fixture_path in gap_fixtures:
        print(f"\n[propose] gap fixture: {stem} (target: {target_rule})")
        base_rule = next((r for r in base_rules.get("rules", [])
                          if r.get("id") == target_rule), None)
        if base_rule is None:
            print(f"[propose] target rule {target_rule} not found in rules.yaml — skipping")
            continue

        candidates = extract_candidate_phrases(fixture_path.read_text(encoding="utf-8"))
        candidates = candidates[:args.max_candidates]
        print(f"[propose] evaluating {len(candidates)} candidate phrase(s)...")

        best = None
        for cand in candidates:
            mutated = mutation_regex_alternation_extend(base_rule, cand)
            if mutated is None:
                continue
            new_rules = make_candidate_rules(base_rules, target_rule, mutated)
            info = score_candidate(new_rules, baseline, gap_fixtures=[stem])
            tag = "✓" if info["score"] > 0 else ("·" if info["score"] == 0 else "✗")
            print(f"  {tag} '{cand}' → score={info['score']} ({info['reason']})")
            if info["score"] != float("-inf") and info["score"] > 0:
                # Tiebreak: prefer longer (more specific) candidates so the
                # mutation doesn't over-fire in the wild on a single common token.
                cand_specificity = len(cand.split())
                better = (best is None
                          or info["score"] > best["score"]
                          or (info["score"] == best["score"]
                              and cand_specificity > best["specificity"]))
                if better:
                    best = {"score": info["score"], "candidate": cand,
                            "mutated": mutated, "info": info,
                            "specificity": cand_specificity}

        if best is None:
            print(f"[propose] No mutation closed gap {stem} without regressions.")
            continue

        if args.dry_run:
            print(f"\n[propose] (dry-run) Best mutation for {stem}: extend {target_rule} "
                  f"with '{best['candidate']}' (score={best['score']})")
            print(dump_yaml({"before": base_rule, "after": best["mutated"]}))
        else:
            out = write_proposal(target_rule, stem, base_rule, best["mutated"],
                                  best["candidate"], best["info"], PROPOSALS_DIR)
            proposals_written.append(out)
            print(f"[propose] Proposal written: {out.relative_to(REPO_ROOT)}")

    if proposals_written:
        print(f"\n[propose] Wrote {len(proposals_written)} proposal(s). "
              "Review under harness/proposals/ before applying.")


if __name__ == "__main__":
    main()
