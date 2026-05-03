#!/usr/bin/env python3
"""
Insight Forge — Codex CLI session extractor.

Locates ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl, filters by cwd
(found inside <environment_context> blocks), applies the noise filter,
and emits a normalized event stream.

USAGE:
    python3 extract_codex.py [--project PATH] [--since ISO8601]
                             [--out PATH] [--include-archived]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


# ============================================================
# CWD detection
# ============================================================

CWD_PATTERNS = [
    re.compile(r"<cwd>\s*(.+?)\s*</cwd>", re.IGNORECASE),
    re.compile(r"Working directory:\s*(\S+)", re.IGNORECASE),
    re.compile(r"<environment_context>.*?<cwd>\s*(.+?)\s*</cwd>", re.IGNORECASE | re.DOTALL),
    re.compile(r'"cwd"\s*:\s*"([^"]+)"'),
]


def normalize_path(p: str) -> str:
    """Normalize a path for cross-platform comparison."""
    if not p:
        return ""
    # Strip extended-length prefix on Windows
    if p.startswith("\\\\?\\"):
        p = p[4:]
    # Normalize separators
    p = p.replace("\\", "/").rstrip("/")
    # Lowercase drive letter on Windows
    if len(p) >= 2 and p[1] == ":":
        p = p[0].upper() + p[1:]
    return p


def session_cwd_matches(jsonl_path: Path, target_cwd: str, max_lines: int = 30,
                        fuzzy: bool = False) -> bool:
    """Read the first ~30 lines of a rollout to find the cwd.

    By default (fuzzy=False) only an exact cwd match is accepted.
    Pass fuzzy=True to also accept parent/child directory matches (pre-v1 behaviour).
    """
    target = normalize_path(target_cwd)
    if not target:
        return False

    def _matches(found: str) -> bool:
        if fuzzy:
            return found == target or found.startswith(target + "/") or target.startswith(found + "/")
        return found == target

    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                # Try structured regex patterns first
                for pattern in CWD_PATTERNS:
                    m = pattern.search(line)
                    if m:
                        found = normalize_path(m.group(1))
                        if _matches(found):
                            return True
                # Quoted-value fallback: only match when the path appears as a quoted string
                # to avoid false positives from parent paths appearing as substrings.
                if f'"{target}"' in line or f"'{target}'" in line:
                    return True
    except Exception:
        return False
    return False


# ============================================================
# Noise filter (Codex variant)
# ============================================================

NOISE_SUBSTRINGS = [
    "<environment_context>",
    "<task-notification>",
    "Base directory for this skill:",
]

EXPLORATION_TOOLS = {"read_file", "list_dir", "list_directory", "grep", "find_files"}

DECISIVE_TOOLS = {"shell", "apply_patch", "edit_file", "write_file"}


def is_noise(content_str: str) -> bool:
    if not content_str or not content_str.strip():
        return True
    for s in NOISE_SUBSTRINGS:
        if s in content_str:
            return True
    return False


def truncate_long_output(text: str, max_lines: int = 100) -> str:
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    head = "\n".join(lines[:30])
    tail = "\n".join(lines[-10:])
    return f"{head}\n... [truncated {len(lines) - 40} lines] ...\n{tail}"


# ============================================================
# Per-line normalization
# ============================================================

def parse_line(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def extract_text_from_content(content) -> str:
    """Pull textual content from Codex response_item content arrays."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("type")
                if t in ("text", "input_text", "output_text"):
                    parts.append(block.get("text", ""))
                elif t == "image" or t == "input_image":
                    parts.append("[image]")
                else:
                    # Unknown block type — keep its text field if any
                    if "text" in block:
                        parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def normalize_codex_line(obj: dict, session_meta: dict) -> Optional[dict]:
    """Map a Codex JSONL line to the pivot schema."""
    line_type = obj.get("type") or obj.get("kind")

    # SessionMeta line — return None (consumed separately by extractor)
    if line_type in ("session_meta", "session_header"):
        return None

    # EventMsg line
    if line_type == "event_msg":
        msg = obj.get("msg", {})
        msg_type = msg.get("type") if isinstance(msg, dict) else None
        # Most event_msg types are infrastructure; only keep boundaries
        if msg_type not in ("task_started", "task_complete"):
            return None
        return {
            "agent": "codex",
            "session_id": session_meta.get("session_id", ""),
            "session_short": session_meta.get("session_short", ""),
            "timestamp": session_meta.get("timestamp", ""),
            "role": "system",
            "content": f"[event:{msg_type}]",
            "tool_name": None,
            "tool_status": None,
            "cwd": session_meta.get("cwd", ""),
        }

    # ResponseItem line — the meat
    if line_type == "response_item":
        item = obj.get("item", obj.get("payload", {}))
        if not isinstance(item, dict):
            return None

        item_type = item.get("type") or item.get("role")
        timestamp = obj.get("timestamp") or item.get("timestamp", "")

        # Plain user/assistant message
        if item_type in ("user", "assistant", "message"):
            role = item.get("role", item_type)
            content = extract_text_from_content(item.get("content", ""))
            if is_noise(content):
                return None
            return {
                "agent": "codex",
                "session_id": session_meta.get("session_id", ""),
                "session_short": session_meta.get("session_short", ""),
                "timestamp": timestamp,
                "role": role,
                "content": content,
                "tool_name": None,
                "tool_status": None,
                "cwd": session_meta.get("cwd", ""),
            }

        # Function/tool call
        if item_type in ("function_call", "tool_call"):
            name = item.get("name", "?")
            args = item.get("arguments", "")
            if isinstance(args, str):
                args_preview = args[:500]
            else:
                args_preview = json.dumps(args, ensure_ascii=False)[:500]
            return {
                "agent": "codex",
                "session_id": session_meta.get("session_id", ""),
                "session_short": session_meta.get("session_short", ""),
                "timestamp": timestamp,
                "role": "tool_use",
                "content": f"[tool_use:{name}] {args_preview}",
                "tool_name": name,
                "tool_status": None,
                "cwd": session_meta.get("cwd", ""),
            }

        # Function/tool result
        if item_type in ("function_call_output", "tool_result"):
            output = item.get("output", "")
            status = item.get("status", "completed")
            output_str = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            output_str = truncate_long_output(output_str, 100)
            err_marker = "[ERROR] " if status == "error" else ""
            return {
                "agent": "codex",
                "session_id": session_meta.get("session_id", ""),
                "session_short": session_meta.get("session_short", ""),
                "timestamp": timestamp,
                "role": "tool_result",
                "content": f"[tool_result] {err_marker}{output_str}",
                "tool_name": None,
                "tool_status": "error" if status == "error" else "ok",
                "cwd": session_meta.get("cwd", ""),
            }

    # Fallback for legacy schemas without explicit type field
    if "role" in obj and "content" in obj:
        text = extract_text_from_content(obj["content"])
        if is_noise(text):
            return None
        return {
            "agent": "codex",
            "session_id": session_meta.get("session_id", ""),
            "session_short": session_meta.get("session_short", ""),
            "timestamp": obj.get("timestamp", ""),
            "role": obj["role"],
            "content": text,
            "tool_name": None,
            "tool_status": None,
            "cwd": session_meta.get("cwd", ""),
        }

    return None


# ============================================================
# Session iteration
# ============================================================

def iter_session(jsonl_path: Path) -> Iterator[dict]:
    """Yield normalized events from a Codex rollout file."""
    session_meta = {
        "session_id": "",
        "session_short": "",
        "timestamp": "",
        "cwd": "",
    }

    with jsonl_path.open(encoding="utf-8", errors="replace") as f:
        # Read first line — should be SessionMeta
        first = f.readline().strip()
        if first:
            obj = parse_line(first)
            if obj:
                if obj.get("type") in ("session_meta", "session_header"):
                    # session_id lives in payload.id in current Codex schema;
                    # fall back to top-level session_id for older formats.
                    payload = obj.get("payload", {})
                    if not isinstance(payload, dict):
                        payload = {}
                    sid = payload.get("id", "") or obj.get("session_id", "")
                    session_meta["session_id"] = sid
                    session_meta["session_short"] = sid[:8] if sid else ""
                    session_meta["timestamp"] = (obj.get("timestamp", "")
                                                 or payload.get("created_at", ""))
                    session_meta["cwd"] = payload.get("cwd", "")
                else:
                    # Not a SessionMeta — process as regular line
                    ev = normalize_codex_line(obj, session_meta)
                    if ev:
                        yield ev

        # Process remaining lines
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = parse_line(line)
            if obj is None:
                continue

            # Search for cwd in user message <environment_context> blocks (lazy fill)
            if not session_meta["cwd"]:
                if obj.get("type") == "response_item":
                    item = obj.get("item", {})
                    content = extract_text_from_content(item.get("content", ""))
                    for pattern in CWD_PATTERNS:
                        m = pattern.search(content)
                        if m:
                            session_meta["cwd"] = normalize_path(m.group(1))
                            break

            ev = normalize_codex_line(obj, session_meta)
            if ev:
                yield ev


def session_metadata(jsonl_path: Path) -> dict:
    """Return summary stats for a Codex session file."""
    size_kb = jsonl_path.stat().st_size // 1024
    mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc).isoformat()

    # Extract session_id from filename: rollout-<TS>-<UUID>.jsonl
    name = jsonl_path.stem
    parts = name.split("-")
    # Last 5 parts joined are the UUID (8-4-4-4-12)
    if len(parts) >= 6:
        session_id = "-".join(parts[-5:])
    else:
        session_id = name

    return {
        "session_id": session_id,
        "session_short": session_id[:8],
        "agent": "codex",
        "file": str(jsonl_path),
        "size_kb": size_kb,
        "mtime": mtime,
    }


def find_codex_sessions(target_cwd: str, codex_home: Path,
                        include_archived: bool = False,
                        fuzzy_cwd: bool = False) -> list[Path]:
    """Locate rollout-*.jsonl files matching the target cwd."""
    roots = [codex_home / "sessions"]
    if include_archived:
        roots.append(codex_home / "archived_sessions")

    matches = []
    for root in roots:
        if not root.exists():
            continue
        for jsonl in root.rglob("rollout-*.jsonl"):
            if session_cwd_matches(jsonl, target_cwd, fuzzy=fuzzy_cwd):
                matches.append(jsonl)

    return sorted(matches, key=lambda p: p.stat().st_mtime)


# ============================================================
# CLI
# ============================================================

def main():
    p = argparse.ArgumentParser(description="Extract Codex CLI sessions for the insight-forge pipeline.")
    p.add_argument("--project", type=str, default=os.getcwd(),
                   help="Project cwd to filter by (default: current directory).")
    p.add_argument("--since", type=str, default=None,
                   help="ISO8601 timestamp; only include sessions modified after.")
    p.add_argument("--out", type=str, default=None,
                   help="Output file path (default: stdout).")
    p.add_argument("--include-archived", action="store_true",
                   help="Also scan ~/.codex/archived_sessions/.")
    p.add_argument("--fuzzy-cwd", action="store_true",
                   help="Also include sessions from parent/child cwd directories (default: exact match only).")
    p.add_argument("--codex-home", type=str, default=None,
                   help="Override ~/.codex location.")
    p.add_argument("--list-only", action="store_true",
                   help="List matching session files without extracting events.")
    args = p.parse_args()

    codex_home = Path(args.codex_home) if args.codex_home else Path.home() / ".codex"
    if not codex_home.exists():
        codex_home_env = os.environ.get("CODEX_HOME")
        if codex_home_env:
            codex_home = Path(codex_home_env)

    files = find_codex_sessions(args.project, codex_home,
                                include_archived=args.include_archived,
                                fuzzy_cwd=args.fuzzy_cwd)

    if not files:
        print(f"[insight-forge] No Codex sessions found for cwd: {args.project}",
              file=sys.stderr)
        print(f"[insight-forge] Scanned: {codex_home / 'sessions'}", file=sys.stderr)
        sys.exit(2)

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
            out_stream.write(json.dumps({"_marker": "session_start", **meta}, ensure_ascii=False) + "\n")
            for ev in iter_session(jsonl):
                out_stream.write(json.dumps(ev, ensure_ascii=False) + "\n")
            out_stream.write(json.dumps({"_marker": "session_end", "session_id": meta["session_id"]}, ensure_ascii=False) + "\n")
    finally:
        if out_stream is not sys.stdout:
            out_stream.close()

    print(f"[insight-forge] Extracted {len(files)} Codex session(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
