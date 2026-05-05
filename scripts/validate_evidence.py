#!/usr/bin/env python3
"""
Insight Forge — evidence bundle validator.

Validates one or more evidence bundle YAML files against
schemas/evidence_bundle.schema.json. With --source <fixture-or-jsonl>, also
verifies that every `quote` in the bundle is a substring of the named source
transcript — making the "rien n'est inventé" promise *executable*, not a
slogan.

USAGE:
    # Validate a single bundle's structure
    python3 scripts/validate_evidence.py path/to/H01.yaml

    # Verify quotes are real (traceability check — the load-bearing test)
    python3 scripts/validate_evidence.py path/to/H01.yaml \\
        --source evals/fixtures/simple_success.jsonl

    # Validate every bundle written by the eval suite for every fixture
    python3 scripts/validate_evidence.py --evals

EXIT CODES:
    0  all bundles valid (and quotes traceable when --source given)
    1  one or more violations
    2  configuration error (missing file, missing schema, etc.)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "evidence_bundle.schema.json"
PIPELINE = REPO_ROOT / "scripts" / "pipeline.py"
FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
EXPECTED_DIR = REPO_ROOT / "evals" / "expected"

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    import jsonschema  # noqa: F401
    from jsonschema import Draft7Validator
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


# ---------------------------------------------------------------------------
# YAML I/O — pyyaml when available, fall back to lite parser
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        return _yaml.safe_load(text) or {}
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from pipeline import yaml_load_simple  # noqa: E402
    return yaml_load_simple(text) or {}


def _load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        sys.stderr.write(f"[validate_evidence] Schema not found: {SCHEMA_PATH}\n")
        sys.exit(2)
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_schema(bundle: dict, schema: dict) -> list[str]:
    """Return a list of validation error messages, empty if valid."""
    if not _HAS_JSONSCHEMA:
        return ["jsonschema not installed — cannot validate structure. "
                "Install with: pip install jsonschema"]
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(bundle), key=lambda e: e.path)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors]


# ---------------------------------------------------------------------------
# Traceability check — quotes must be substrings of the source transcript
# ---------------------------------------------------------------------------

def _extract_source_corpus(source_path: Path) -> str:
    """Concatenate every event's content from a normalized JSONL transcript."""
    pieces = []
    for line in source_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("_marker"):
            continue
        content = obj.get("content")
        if content:
            pieces.append(content)
    return "\n".join(pieces)


def verify_traceability(bundle: dict, source_corpus: str) -> list[str]:
    """Every evidence event with a `quote` must be a substring of the source.
    Returns a list of error messages, empty if all quotes traceable."""
    errors = []
    evidence = bundle.get("evidence") or []
    for i, ev in enumerate(evidence):
        quote = (ev.get("quote") or "").strip()
        if not quote:
            continue
        # The pipeline truncates quotes to ~280 chars and replaces newlines
        # with spaces in the user-facing rendering. The bundle stores the
        # raw stored value — which may have been truncated. We do a
        # substring check on the trimmed raw quote against the corpus, with
        # a fallback that compares the un-truncated tail less the ellipsis.
        if quote in source_corpus:
            continue
        # Tolerate trailing ellipsis from _truncate_at_word
        candidate = quote.rstrip("…").rstrip()
        if candidate and candidate in source_corpus:
            continue
        errors.append(f"evidence[{i}] quote not found in source: "
                      f"{quote[:80]!r}{'…' if len(quote) > 80 else ''}")
    return errors


# ---------------------------------------------------------------------------
# --evals mode: run the full eval suite, validate every bundle produced
# ---------------------------------------------------------------------------

def run_pipeline_on_fixture(fixture: Path) -> Path:
    forge_dir = Path(tempfile.mkdtemp(prefix=f"forge-validate-{fixture.stem}-"))
    cmd = [sys.executable, str(PIPELINE),
           "--input", str(fixture),
           "--forge-dir", str(forge_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(f"pipeline.py failed on {fixture.name}")
    return forge_dir


def validate_evals_mode(schema: dict) -> int:
    """Run every fixture through the pipeline, validate every bundle produced
    against the schema, and verify every quote is traceable to that fixture.

    Skips known-gap fixtures (they don't promote, so no bundle to validate).
    """
    violations = 0
    bundles_seen = 0
    for fixture in sorted(FIXTURES_DIR.glob("*.jsonl")):
        expected_path = EXPECTED_DIR / f"{fixture.stem}.expected.yaml"
        if not expected_path.exists():
            continue
        expected = _load_yaml(expected_path)
        if expected.get("known_gap"):
            continue

        forge_dir = run_pipeline_on_fixture(fixture)
        try:
            corpus = _extract_source_corpus(fixture)
            bundles_dir = forge_dir / "evidence" / "bundles"
            for bundle_path in sorted(bundles_dir.glob("*.yaml")):
                if bundle_path.name == "README.md" or bundle_path.stem.lower() == "readme":
                    continue
                bundle = _load_yaml(bundle_path)
                schema_errs = validate_schema(bundle, schema)
                trace_errs = verify_traceability(bundle, corpus)
                bundles_seen += 1
                if schema_errs or trace_errs:
                    violations += 1
                    print(f"  ✗ {fixture.stem} → {bundle_path.name}")
                    for e in schema_errs:
                        print(f"      schema: {e}")
                    for e in trace_errs:
                        print(f"      trace:  {e}")
                else:
                    print(f"  ✓ {fixture.stem} → {bundle_path.name}")
        finally:
            shutil.rmtree(forge_dir, ignore_errors=True)

    print()
    if violations:
        print(f"  {violations} bundle(s) failed validation out of {bundles_seen}")
    else:
        print(f"  all {bundles_seen} bundles valid (schema + quote traceability)")
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=(
        "Validate insight-forge evidence bundles against the JSON Schema, and "
        "(optionally) verify each quote is a substring of a source transcript."
    ))
    p.add_argument("bundle", nargs="?", default=None,
                   help="Path to a single bundle YAML file. Omit when using --evals.")
    p.add_argument("--source", default=None,
                   help="JSONL source to verify quote traceability against.")
    p.add_argument("--evals", action="store_true",
                   help="Run the full eval suite, validate every bundle produced.")
    args = p.parse_args()

    schema = _load_schema()

    if args.evals:
        sys.exit(0 if validate_evals_mode(schema) == 0 else 1)

    if not args.bundle:
        p.print_usage(sys.stderr)
        sys.stderr.write("\nProvide either a bundle path or --evals\n")
        sys.exit(2)

    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        sys.stderr.write(f"[validate_evidence] Bundle not found: {bundle_path}\n")
        sys.exit(2)

    bundle = _load_yaml(bundle_path)
    schema_errs = validate_schema(bundle, schema)

    trace_errs: list[str] = []
    if args.source:
        source_path = Path(args.source)
        if not source_path.exists():
            sys.stderr.write(f"[validate_evidence] Source not found: {source_path}\n")
            sys.exit(2)
        corpus = _extract_source_corpus(source_path)
        trace_errs = verify_traceability(bundle, corpus)

    if schema_errs or trace_errs:
        for e in schema_errs:
            print(f"  schema: {e}")
        for e in trace_errs:
            print(f"  trace:  {e}")
        sys.exit(1)
    else:
        msg = "schema valid"
        if args.source:
            msg += " and all quotes traceable to source"
        print(f"  ✓ {bundle_path.name} — {msg}")


if __name__ == "__main__":
    main()
