"""
insight-forge — CLI entry point.

Exposes the most common workflows as named subcommands. The implementation
is intentionally a thin dispatcher: each subcommand resolves to one of the
existing scripts under `scripts/` and execs it as a subprocess. This keeps
the script-oriented layout intact while giving installed users a friendlier
surface than `python3 scripts/run_evals.py --verify-contracts`.

USAGE:
    insight-forge                              # default = scan
    insight-forge scan [--rebuild|--challenge|--since|--fuzzy-cwd|...]
    insight-forge eval [--fixture|--json|--verify-contracts|--rules-path|...]
    insight-forge propose [--dry-run|--target-fixture|--max-candidates]
    insight-forge validate-evidence [BUNDLE] [--evals|--source PATH]
    insight-forge doctor
    insight-forge --version

Run `insight-forge <subcommand> --help` to see the underlying script's flags.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from insight_forge import __version__

# Resolve scripts/ relative to the repo root, regardless of where the user
# invokes the CLI from. The repo root is the parent of the `insight_forge`
# package directory.
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
SCRIPTS = _REPO_ROOT / "scripts"


def _exec_script(script_name: str, passthrough_args: list[str]) -> int:
    """Run scripts/<name>.py with the user's args, streaming stdout/stderr."""
    script = SCRIPTS / script_name
    if not script.exists():
        print(f"insight-forge: script not found: {script}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(script), *passthrough_args]
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# `doctor` — environment diagnostic. Implemented inline because there's no
# corresponding script to delegate to.
# ---------------------------------------------------------------------------

def cmd_doctor(_args: argparse.Namespace) -> int:
    """Sanity-check the local environment and report status to the user."""
    rows: list[tuple[str, str, str]] = []  # (label, status, detail)

    py_ver = sys.version_info
    py_ok = py_ver >= (3, 10)
    rows.append(("Python", "OK" if py_ok else "FAIL",
                  f"{py_ver.major}.{py_ver.minor}.{py_ver.micro} "
                  f"(requires >= 3.10)"))

    try:
        import yaml  # noqa: F401
        rows.append(("PyYAML", "OK", "available (fast path)"))
    except ImportError:
        rows.append(("PyYAML", "WARN",
                      "not installed — falls back to lite parser. "
                      "pip install pyyaml for the fast path"))

    try:
        import jsonschema  # noqa: F401
        rows.append(("jsonschema", "OK", "available (evidence validator)"))
    except ImportError:
        rows.append(("jsonschema", "WARN",
                      "not installed — `validate-evidence` will degrade. "
                      "pip install jsonschema"))

    claude_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
    claude_dir = claude_home / "projects"
    rows.append(("~/.claude/projects",
                  "OK" if claude_dir.exists() else "WARN",
                  str(claude_dir) +
                  (" — exists" if claude_dir.exists()
                   else " — not found (no Claude Code sessions yet)")))

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    codex_dir = codex_home / "sessions"
    rows.append(("~/.codex/sessions",
                  "OK" if codex_dir.exists() else "WARN",
                  str(codex_dir) +
                  (" — exists" if codex_dir.exists()
                   else " — not found (no Codex CLI sessions yet)")))

    rules_path = _REPO_ROOT / "harness" / "rules.yaml"
    rules_ok = rules_path.exists()
    rules_detail = str(rules_path)
    if rules_ok:
        try:
            sys.path.insert(0, str(_REPO_ROOT))
            from harness.loader import load_rules  # noqa: E402
            rs = load_rules(rules_path)
            rules_detail = f"loaded {len(rs.rules)} rule(s)"
        except Exception as exc:
            rules_ok = False
            rules_detail = f"failed to parse: {exc}"
    rows.append(("harness/rules.yaml",
                  "OK" if rules_ok else "FAIL", rules_detail))

    schema_path = _REPO_ROOT / "schemas" / "evidence_bundle.schema.json"
    rows.append(("evidence schema",
                  "OK" if schema_path.exists() else "FAIL",
                  str(schema_path)))

    fixtures_count = len(list((_REPO_ROOT / "evals" / "fixtures").glob("*.jsonl")))
    rows.append(("evals/fixtures",
                  "OK" if fixtures_count > 0 else "WARN",
                  f"{fixtures_count} fixture(s)"))

    last_run = Path.cwd() / ".insight-forge" / ".last_run"
    if last_run.exists():
        rows.append(("last run cursor", "OK",
                      last_run.read_text(encoding="utf-8").splitlines()[0]
                      if last_run.read_text(encoding="utf-8").strip() else "(empty)"))
    else:
        rows.append(("last run cursor", "INFO",
                      "no .insight-forge/.last_run yet — first run will scan everything"))

    # --- render ----------------------------------------------------------
    label_w = max(len(r[0]) for r in rows)
    status_w = 4
    print()
    print("  insight-forge — environment diagnostic")
    print("  " + "─" * 56)
    overall_ok = True
    for label, status, detail in rows:
        mark = {"OK": "✓", "WARN": "⚠", "FAIL": "✗", "INFO": "·"}[status]
        if status == "FAIL":
            overall_ok = False
        print(f"  {mark} {label:<{label_w}} {status:<{status_w}}  {detail}")
    print()
    if overall_ok:
        print("  doctor: ready")
    else:
        print("  doctor: at least one critical check failed")
    print()
    return 0 if overall_ok else 1


# ---------------------------------------------------------------------------
# Subcommand wiring
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="insight-forge",
        description="Cross-session ARA-style learner. Reads JSONL transcripts "
                     "from Claude Code or Codex CLI, crystallizes typed "
                     "knowledge, proposes CLAUDE.md / AGENTS.md diffs.",
        epilog="Run `insight-forge <subcommand> --help` to see the underlying "
                "script's flags.",
    )
    parser.add_argument("--version", action="version",
                         version=f"insight-forge {__version__}")
    sub = parser.add_subparsers(dest="command")

    # `scan` — run.py
    sub.add_parser("scan", help="scan new sessions, run pipeline, write proposal "
                                  "(default subcommand)", add_help=False)
    # `eval` — run_evals.py
    sub.add_parser("eval", help="run regression evals + contract verifier",
                    add_help=False)
    # `propose` — propose_rules.py
    sub.add_parser("propose", help="propose harness rule edits from known gaps",
                    add_help=False)
    # `validate-evidence` — validate_evidence.py
    sub.add_parser("validate-evidence",
                    help="validate an evidence bundle against the schema "
                         "(and optionally against its source transcript)",
                    add_help=False)
    # `doctor` — implemented inline
    sub.add_parser("doctor", help="diagnose the local environment")

    # We parse only argv[0] (the subcommand) here, then forward the rest
    # untouched to the underlying script's argparse — this preserves every
    # flag the script supports without redefining it.
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["scan"]

    cmd = argv[0]
    if cmd in ("-h", "--help"):
        parser.print_help()
        return 0
    if cmd in ("-V", "--version"):
        print(f"insight-forge {__version__}")
        return 0

    rest = argv[1:]

    if cmd == "doctor":
        return cmd_doctor(argparse.Namespace())
    if cmd == "scan":
        return _exec_script("run.py", rest)
    if cmd == "eval":
        return _exec_script("run_evals.py", rest)
    if cmd == "propose":
        return _exec_script("propose_rules.py", rest)
    if cmd == "validate-evidence":
        return _exec_script("validate_evidence.py", rest)

    parser.print_usage(sys.stderr)
    print(f"insight-forge: unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
