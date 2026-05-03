#!/usr/bin/env python3
"""
Insight Forge — Claude Code session extractor.

Locates ~/.claude/projects/<encoded-cwd>/*.jsonl, applies the noise filter,
and emits a normalized event stream to stdout (one JSON object per line)
or to --out file.

USAGE:
    python3 extract_claude.py [--project PATH] [--since ISO8601]
                              [--out PATH] [--include-subagents]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


# ============================================================
# CWD encoding
# ============================================================

def encode_cwd_candidates(cwd: str) -> list[str]:
    """Return candidate encoded directory names for a cwd, both POSIX and Windows."""
    p = Path(cwd).resolve()
    s = str(p)
    candidates = []

    # POSIX style: /Users/jp/foo → -Users-jp-foo
    if s.startswith("/"):
        candidates.append(s.replace("/", "-"))

    # Windows style: D:\DEV\foo → D--DEV-foo
    if len(s) >= 2 and s[1] == ":":
        candidates.append(s.replace("\\", "-").replace(":", "-"))
        # Some variants without the colon repeat
        candidates.append(s.replace("\\", "-").replace(":", ""))

    # On any platform, also try a normalized form just in case
    candidates.append(s.replace(os.sep, "-").replace(":", "-"))

    # Dedupe while preserving order
    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def find_project_dir(cwd: str, claude_home: Path) -> Optional[Path]:
    projects_root = claude_home / "projects"
    if not projects_root.exists():
        return None

    for candidate in encode_cwd_candidates(cwd):
        proj = projects_root / candidate
        if proj.is_dir():
            return proj
    return None


def fuzzy_suggest(cwd: str, claude_home: Path, n: int = 5) -> list[str]:
    """When no exact match, suggest similar directory names."""
    projects_root = claude_home / "projects"
    if not projects_root.exists():
        return []

    candidates = encode_cwd_candidates(cwd)
    target = candidates[0] if candidates else cwd

    all_dirs = [d.name for d in projects_root.iterdir() if d.is_dir()]
    # Crude similarity: count common substrings
    def score(d):
        parts_target = set(target.split("-"))
        parts_d = set(d.split("-"))
        return len(parts_target & parts_d)

    return sorted(all_dirs, key=score, reverse=True)[:n]


# ============================================================
# Noise filter
# ============================================================

NOISE_SUBSTRINGS = [
    "Hook PreToolUse:",
    "Hook PostToolUse:",
    "Base directory for this skill:",
    "<system-reminder>",
    "<task-notification>",
]

EXPLORATION_TOOLS = {"Read", "Glob", "Grep", "LS"}

DECISIVE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}


def is_noise(content_str: str) -> bool:
    """Drop messages that are pure plumbing."""
    if not content_str or not content_str.strip():
        return True
    for s in NOISE_SUBSTRINGS:
        if s in content_str:
            return True
    return False


def truncate_long_output(text: str, max_lines: int = 100) -> str:
    """Keep first 30 + last 10 lines if longer than max_lines."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    head = "\n".join(lines[:30])
    tail = "\n".join(lines[-10:])
    return f"{head}\n... [truncated {len(lines) - 40} lines] ...\n{tail}"


def extract_text_content(content) -> str:
    """Pull the textual content out of various message shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("type")
                if t == "text":
                    parts.append(block.get("text", ""))
                elif t == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    parts.append(f"[tool_use:{name}] {json.dumps(inp, ensure_ascii=False)[:500]}")
                elif t == "tool_result":
                    out = block.get("content", "")
                    if isinstance(out, list):
                        out = " ".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in out
                        )
                    is_err = block.get("is_error", False)
                    err_marker = "[ERROR] " if is_err else ""
                    parts.append(f"[tool_result] {err_marker}{truncate_long_output(str(out), 100)}")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


# ============================================================
# Per-line extractor
# ============================================================

def parse_line(raw: str) -> Optional[dict]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj


def normalize_message(msg: dict) -> Optional[dict]:
    """Map a Claude Code JSONL line to the pivot schema."""
    msg_type = msg.get("type")

    # Skip auto-compaction summaries
    if msg_type == "summary":
        return None

    timestamp = msg.get("timestamp", "")
    session_id = msg.get("sessionId") or msg.get("session_id", "")
    uuid = msg.get("uuid", "")
    parent_uuid = msg.get("parentUuid") or msg.get("parent_uuid", "")
    cwd = msg.get("cwd", "")
    git_branch = msg.get("gitBranch") or msg.get("git_branch", "")

    # Resolve role
    inner = msg.get("message", {})
    role = inner.get("role") if isinstance(inner, dict) else None
    if not role:
        # Top-level role for tool_use / tool_result variant
        role = msg_type

    content = inner.get("content") if isinstance(inner, dict) else msg.get("content")
    text = extract_text_content(content)

    # Detect tool_use / tool_result via content blocks even if role is "user" or "assistant"
    has_tool_use = isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_use" for b in content
    )
    has_tool_result = isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )

    # Determine the canonical role for the pivot schema
    if has_tool_use:
        canonical = "tool_use"
    elif has_tool_result:
        canonical = "tool_result"
    elif role in ("user", "assistant"):
        canonical = role
    else:
        canonical = role or "unknown"

    # Drop pure noise
    if is_noise(text):
        # But keep tool_use/tool_result even if their text is empty — the structure matters
        if not (has_tool_use or has_tool_result):
            return None

    # Extract tool metadata if present
    tool_name = None
    tool_status = None
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "tool_use":
                    tool_name = b.get("name")
                elif b.get("type") == "tool_result":
                    tool_status = "error" if b.get("is_error") else "ok"

    return {
        "agent": "claude",
        "session_id": session_id,
        "session_short": session_id[:8] if session_id else "",
        "uuid": uuid,
        "parent_uuid": parent_uuid,
        "timestamp": timestamp,
        "role": canonical,
        "content": text,
        "tool_name": tool_name,
        "tool_status": tool_status,
        "cwd": cwd,
        "git_branch": git_branch,
    }


# ============================================================
# Session iteration
# ============================================================

def iter_session(jsonl_path: Path) -> Iterator[dict]:
    with jsonl_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            obj = parse_line(line)
            if obj is None:
                continue
            normalized = normalize_message(obj)
            if normalized is not None:
                yield normalized


def session_metadata(jsonl_path: Path) -> dict:
    """Return summary stats for a session file (used for session_index)."""
    size_kb = jsonl_path.stat().st_size // 1024
    mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc).isoformat()
    session_id = jsonl_path.stem  # filename without .jsonl extension
    return {
        "session_id": session_id,
        "session_short": session_id[:8],
        "agent": "claude",
        "file": str(jsonl_path),
        "size_kb": size_kb,
        "mtime": mtime,
    }


# ============================================================
# CLI
# ============================================================

def main():
    p = argparse.ArgumentParser(description="Extract Claude Code sessions for the insight-forge pipeline.")
    p.add_argument("--project", type=str, default=os.getcwd(),
                   help="Project cwd to filter by (default: current directory).")
    p.add_argument("--since", type=str, default=None,
                   help="ISO8601 timestamp; only include sessions modified after.")
    p.add_argument("--out", type=str, default=None,
                   help="Output file path (default: stdout).")
    p.add_argument("--include-subagents", action="store_true",
                   help="Recurse into subagent transcripts (off by default).")
    p.add_argument("--claude-home", type=str, default=None,
                   help="Override ~/.claude location.")
    p.add_argument("--list-only", action="store_true",
                   help="List matching session files without extracting events.")
    args = p.parse_args()

    claude_home = Path(args.claude_home) if args.claude_home else Path.home() / ".claude"
    project_dir = find_project_dir(args.project, claude_home)

    if project_dir is None:
        print(f"[insight-forge] No Claude Code sessions found for cwd: {args.project}",
              file=sys.stderr)
        suggestions = fuzzy_suggest(args.project, claude_home)
        if suggestions:
            print("[insight-forge] Did you mean one of:", file=sys.stderr)
            for s in suggestions:
                print(f"  - {s}", file=sys.stderr)
        sys.exit(2)

    # Find session files, sorted by mtime
    files = sorted(project_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)

    # Apply --since filter
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        except ValueError:
            print(f"[insight-forge] Invalid --since timestamp: {args.since}", file=sys.stderr)
            sys.exit(1)
        files = [
            f for f in files
            if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) > since_dt
        ]

    if args.list_only:
        for f in files:
            print(f)
        return

    out_stream = sys.stdout
    if args.out:
        out_stream = open(args.out, "w", encoding="utf-8")

    try:
        for jsonl in files:
            meta = session_metadata(jsonl)
            # Emit a session header marker
            out_stream.write(json.dumps({"_marker": "session_start", **meta}, ensure_ascii=False) + "\n")
            for ev in iter_session(jsonl):
                out_stream.write(json.dumps(ev, ensure_ascii=False) + "\n")
            out_stream.write(json.dumps({"_marker": "session_end", "session_id": meta["session_id"]}, ensure_ascii=False) + "\n")
    finally:
        if out_stream is not sys.stdout:
            out_stream.close()

    print(f"[insight-forge] Extracted {len(files)} session(s) from {project_dir}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
