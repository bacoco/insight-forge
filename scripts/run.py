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
import json
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
            print("[insight-forge] No Claude Code or Codex sessions found on this machine.",
                  file=sys.stderr)
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
        print("[insight-forge] No new sessions to process since last run. Nothing to do.",
              file=sys.stderr)
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
    proposal_cmd = [sys.executable, str(SCRIPTS / "propose_claude_md.py"),
                    "--forge-dir", str(forge_dir)]
    if since:
        # Pass date-only portion so proposal filters to new knowledge
        proposal_cmd += ["--since", since[:10]]
    result = subprocess.run(proposal_cmd, capture_output=True, text=True)
    proposal_path = result.stdout.strip()
    if result.returncode == 0 and proposal_path:
        print(f"[insight-forge] Proposal ready: {proposal_path}", file=sys.stderr)
    else:
        print("[insight-forge] Warning: proposal generation failed", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

    # ── Print summary ─────────────────────────────────────────
    summary_path = forge_dir / "trace" / "pipeline_log.yaml"
    summary_line = ""
    if summary_path.exists():
        lines = summary_path.read_text(encoding="utf-8").splitlines()
        # Last run entry is at the bottom — grab the key counts
        for line in reversed(lines):
            if "candidates:" in line or "crystallized:" in line:
                summary_line = line.strip()
                break

    agents_str = " + ".join(agents)
    print(f"\n[insight-forge] Done ({agents_str}) — {summary_line}", file=sys.stderr)
    if proposal_path:
        print(f"[insight-forge] → Review: {proposal_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
