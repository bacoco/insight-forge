#!/usr/bin/env python3
"""
Insight Forge — single-command incremental orchestrator.

Replaces the 8-step manual procedure with one command. Reads .last_run,
calls only the extractor(s) needed with --since <last_run>, runs the
pipeline, then writes the proposal. Sessions already processed are never
re-read.

USAGE:
    python3 scripts/run.py [OPTIONS]

OPTIONS:
    --project PATH          Project root to scan (default: cwd)
    --forge-dir PATH        .insight-forge directory (default: <project>/.insight-forge)
    --agent auto|claude|codex
                            Which agent's sessions to scan (default: auto-detect)
    --since ISO8601         Override .last_run cursor manually
    --rebuild               Wipe .insight-forge and reprocess all sessions from scratch
    --challenge             Run Devil's Advocate sweep after crystallization
    --fuzzy-cwd             Codex: also include parent/child cwd sessions
    --exclude-session ID    Codex: exclude session by id prefix (repeatable)
    --active-grace SECONDS  Codex: skip sessions modified within N seconds (default: 60)
    --claude-home PATH      Override ~/.claude location
    --codex-home PATH       Override ~/.codex location
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# Helpers
# ============================================================

SCRIPTS = Path(__file__).parent


def _run(cmd: list[str], label: str) -> subprocess.CompletedProcess:
    """Run a subprocess, stream stderr, raise on failure."""
    print(f"[insight-forge] {label}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode not in (0, 2):  # 2 = "no sessions found" (non-fatal)
        print(f"[insight-forge] ERROR: {label} exited {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    return result


def read_last_run(forge_dir: Path) -> str | None:
    """Return the ISO timestamp from .last_run, or None on first run."""
    p = forge_dir / ".last_run"
    if not p.exists():
        return None
    first_line = p.read_text(encoding="utf-8").splitlines()[0].strip()
    return first_line or None


def detect_agents(claude_home: Path, codex_home: Path) -> list[str]:
    """Return which agents have session directories on disk."""
    found = []
    if (claude_home / "projects").exists():
        found.append("claude")
    if (codex_home / "sessions").exists():
        found.append("codex")
    return found


def _print_no_sessions_help(claude_home: Path, codex_home: Path) -> None:
    """Print actionable empty-state guidance instead of a bare error."""
    sys.stderr.write("\n")
    sys.stderr.write("  Insight Forge couldn't find any AI coding sessions on this machine.\n\n")
    sys.stderr.write("  insight-forge analyzes the JSONL transcripts your AI assistant writes\n")
    sys.stderr.write("  while you work. It looks in two places:\n\n")
    sys.stderr.write(f"    Claude Code: {claude_home}/projects/\n")
    sys.stderr.write(f"    Codex CLI:   {codex_home}/sessions/\n\n")
    sys.stderr.write("  Neither directory exists yet on this machine.\n\n")
    sys.stderr.write("  What to do next:\n")
    sys.stderr.write("    1. Use Claude Code or Codex CLI for a few minutes in any project.\n")
    sys.stderr.write("       Sessions are saved automatically as you go.\n")
    sys.stderr.write("    2. Re-run insight-forge from inside that project's directory.\n\n")
    sys.stderr.write("  Already used your AI here but still seeing this? Try:\n")
    sys.stderr.write("    python3 scripts/run.py --fuzzy-cwd\n\n")
    sys.stderr.write("  (matches sessions whose recorded cwd is a parent or child of yours.)\n\n")


def extract(agent: str, project: str, since: str | None,
            out: Path, args: argparse.Namespace) -> bool:
    """Call the right extractor. Returns True if it produced output."""
    cmd = [sys.executable, str(SCRIPTS / f"extract_{agent}.py"),
           "--project", project,
           "--out", str(out)]
    if since:
        cmd += ["--since", since]
    if agent == "codex":
        if args.fuzzy_cwd:
            cmd.append("--fuzzy-cwd")
        for sid in (args.exclude_sessions or []):
            cmd += ["--exclude-session", sid]
        cmd += ["--active-grace", str(args.active_grace)]
        if args.codex_home:
            cmd += ["--codex-home", args.codex_home]
    if agent == "claude" and args.claude_home:
        cmd += ["--claude-home", args.claude_home]

    result = subprocess.run(cmd, text=True)
    # exit code 2 = no sessions found for this agent (non-fatal)
    if result.returncode == 2:
        print(f"[insight-forge] No {agent} sessions found — skipping", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"[insight-forge] Extractor for {agent} failed (exit {result.returncode})",
              file=sys.stderr)
        sys.exit(result.returncode)
    return out.exists() and out.stat().st_size > 0


def merge_normalized(parts: list[Path], dest: Path):
    """Concatenate multiple normalized.jsonl files into one."""
    with dest.open("w", encoding="utf-8") as out:
        for p in parts:
            if p.exists():
                out.write(p.read_text(encoding="utf-8"))


# ============================================================
# Main
# ============================================================

def main():
    p = argparse.ArgumentParser(
        description="Insight Forge incremental orchestrator — one command to run the full pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project", default=os.getcwd(),
                   help="Project root to scan (default: cwd).")
    p.add_argument("--forge-dir", default=None,
                   help="Path to .insight-forge/ (default: <project>/.insight-forge).")
    p.add_argument("--agent", default="auto", choices=["auto", "claude", "codex"],
                   help="Agent whose sessions to scan (default: auto-detect).")
    p.add_argument("--since", default=None,
                   help="Override .last_run cursor with an explicit ISO8601 timestamp.")
    p.add_argument("--rebuild", action="store_true",
                   help="Wipe .insight-forge and reprocess all sessions from scratch.")
    p.add_argument("--challenge", action="store_true",
                   help="Run Devil's Advocate sweep after crystallization.")
    p.add_argument("--fuzzy-cwd", action="store_true",
                   help="Codex: also match parent/child cwd sessions.")
    p.add_argument("--exclude-session", action="append", dest="exclude_sessions",
                   metavar="ID", default=[],
                   help="Codex: exclude session by id prefix (repeatable).")
    p.add_argument("--active-grace", type=int, default=60, metavar="SECONDS",
                   help="Codex: skip sessions modified within N seconds (default: 60).")
    p.add_argument("--claude-home", default=None, help="Override ~/.claude location.")
    p.add_argument("--codex-home", default=None, help="Override ~/.codex location.")
    p.add_argument("--redact", action="store_true",
                   help="Redact likely secrets in the proposal (forwarded to "
                        "propose_claude_md.py). Use before sharing a proposal.")
    args = p.parse_args()

    project = str(Path(args.project).resolve())
    forge_dir = Path(args.forge_dir) if args.forge_dir else Path(project) / ".insight-forge"
    forge_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = forge_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)

    claude_home = Path(args.claude_home) if args.claude_home else Path.home() / ".claude"
    codex_home = Path(args.codex_home) if args.codex_home else Path.home() / ".codex"

    # ── Determine agents to scan ──────────────────────────────
    if args.agent == "auto":
        agents = detect_agents(claude_home, codex_home)
        if not agents:
            _print_no_sessions_help(claude_home, codex_home)
            sys.exit(1)
    else:
        agents = [args.agent]

    # ── Determine --since cursor ──────────────────────────────
    if args.rebuild:
        since = None
        print("[insight-forge] --rebuild: ignoring .last_run, will reprocess all sessions",
              file=sys.stderr)
    elif args.since:
        since = args.since
        print(f"[insight-forge] Using explicit --since: {since}", file=sys.stderr)
    else:
        since = read_last_run(forge_dir)
        if since:
            print(f"[insight-forge] Incremental run — processing sessions since {since}",
                  file=sys.stderr)
        else:
            print("[insight-forge] First run — processing all sessions", file=sys.stderr)

    # ── Run extractors ────────────────────────────────────────
    extracted_parts: list[Path] = []
    for agent in agents:
        out = cache_dir / f"normalized_{agent}.jsonl"
        ok = extract(agent, project, since, out, args)
        if ok:
            extracted_parts.append(out)

    if not extracted_parts:
        sys.stderr.write("\n")
        if since:
            sys.stderr.write(f"  No new sessions since {since[:10]}.\n")
            sys.stderr.write(f"  insight-forge stays incremental — nothing to do until you\n")
            sys.stderr.write(f"  use your AI assistant again in this project.\n\n")
        else:
            sys.stderr.write(f"  No sessions found for this project's directory.\n")
            sys.stderr.write(f"    Project: {project}\n\n")
            sys.stderr.write(f"  If you have used your AI from a parent or sibling directory,\n")
            sys.stderr.write(f"  try:  python3 scripts/run.py --fuzzy-cwd\n\n")
        # Still update .last_run so the cursor advances
        last_run_file = forge_dir / ".last_run"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        last_run_file.write_text(f"{now}\nlast_session: \n", encoding="utf-8")
        sys.exit(0)

    # ── Merge if both agents ──────────────────────────────────
    normalized = cache_dir / "normalized.jsonl"
    if len(extracted_parts) == 1:
        extracted_parts[0].rename(normalized)
    else:
        merge_normalized(extracted_parts, normalized)
        for part in extracted_parts:
            if part.exists():
                part.unlink()

    # ── Run pipeline ──────────────────────────────────────────
    pipeline_cmd = [sys.executable, str(SCRIPTS / "pipeline.py"),
                    "--input", str(normalized),
                    "--forge-dir", str(forge_dir)]
    if args.rebuild:
        pipeline_cmd.append("--rebuild")
    if args.challenge:
        pipeline_cmd.append("--challenge")
    _run(pipeline_cmd, "Running pipeline (Harvester → Router → Maturity Tracker)…")

    # ── Generate proposal ─────────────────────────────────────
    # Capture stdout (the path) but let stderr flow through so the user
    # sees the friendly summary printed by propose_claude_md.py.
    proposal_cmd = [sys.executable, str(SCRIPTS / "propose_claude_md.py"),
                    "--forge-dir", str(forge_dir)]
    if since:
        # Pass date-only portion so proposal filters to new knowledge
        proposal_cmd += ["--since", since[:10]]
    if args.redact:
        proposal_cmd.append("--redact")
    result = subprocess.run(proposal_cmd, stdout=subprocess.PIPE, text=True)
    proposal_path = (result.stdout or "").strip()
    if result.returncode != 0:
        print("[insight-forge] Warning: proposal generation failed", file=sys.stderr)


if __name__ == "__main__":
    main()
