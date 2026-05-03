#!/usr/bin/env python3
"""
Insight Forge — render an iMessage-style HTML annex of sessions.

Two modes:
- Whole-project: renders all sessions in session_index into evidence/sessions.html
- Focused: --entry C03 renders only the sessions that fed claim C03

USAGE:
    python3 render_evidence.py [--forge-dir .insight-forge] [--entry ID]
                               [--input <normalized.jsonl>]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TEMPLATE_PATH_DEFAULT = Path(__file__).parent.parent / "templates" / "imessage_template.html"


def escape(s: str) -> str:
    return html.escape(s or "", quote=False)


def render_message(ev: dict) -> str:
    """Render one event as a chat bubble."""
    role = ev.get("role", "")
    content = ev.get("content", "")
    ts = ev.get("timestamp", "")
    short_ts = ts[11:16] if len(ts) >= 16 else ts

    css_role = role
    extra_class = ""
    if role == "tool_result" and ev.get("tool_status") == "error":
        extra_class = " error"
    if role not in ("user", "assistant", "tool_use", "tool_result"):
        # Fallback for unknown roles — render as marker
        return f'<div class="marker">[{escape(role)}] {escape(content[:200])}</div>'

    bubble = escape(content)
    return (
        f'<div class="msg {css_role}{extra_class}">\n'
        f'  <div class="bubble">{bubble}</div>\n'
        f'  <div class="meta-row">{escape(short_ts)}</div>\n'
        f'</div>\n'
    )


def render_session(session_meta: dict, events: list[dict]) -> str:
    out = []
    sid = session_meta.get("session_short", session_meta.get("session_id", "?"))[:8]
    agent = session_meta.get("agent", "?")
    date = session_meta.get("mtime", "")[:10]
    size_kb = session_meta.get("size_kb", "?")
    out.append('<div class="session">')
    out.append('<div class="session-header">')
    out.append(f'  <strong>Session {escape(sid)}</strong> &nbsp;|&nbsp; ')
    out.append(f'agent: {escape(agent)} &nbsp;|&nbsp; date: {escape(date)} &nbsp;|&nbsp; size: {size_kb} KB &nbsp;|&nbsp; events: {len(events)}')
    out.append('</div>')
    last_date = ""
    for ev in events:
        ts = ev.get("timestamp", "")
        ev_date = ts[:10]
        if ev_date and ev_date != last_date:
            out.append(f'<div class="day-divider">{escape(ev_date)}</div>')
            last_date = ev_date
        out.append(render_message(ev))
    out.append('</div>\n')
    return "\n".join(out)


def load_normalized(path: Path) -> tuple[list[dict], list[list[dict]]]:
    """Return (session_metas, list_of_events_per_session)."""
    metas = []
    sessions = []
    current_meta = None
    current_events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            marker = obj.get("_marker")
            if marker == "session_start":
                current_meta = {k: v for k, v in obj.items() if k != "_marker"}
                metas.append(current_meta)
                current_events = []
                sessions.append(current_events)
            elif marker == "session_end":
                pass
            else:
                current_events.append(obj)
    return metas, sessions


def filter_by_entry(forge_dir: Path, entry_id: str,
                    metas: list[dict], sessions: list[list[dict]]) -> tuple[list[dict], list[list[dict]]]:
    """Keep only sessions whose IDs are referenced by the given entry."""
    # Look up the entry in logic/*.md
    target_files = ["claims.md", "heuristics.md", "dead_ends.md", "concepts.md"]
    referenced_ids = set()
    for tf in target_files:
        p = forge_dir / "logic" / tf
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        # Find the entry block
        m = re.search(rf"^## {re.escape(entry_id)}:.*?(?=^## |\Z)", text,
                      re.MULTILINE | re.DOTALL)
        if not m:
            continue
        block = m.group(0)
        # Extract session IDs from the Sessions field
        sm = re.search(r"\*\*Sessions\*\*:\s*\[(.*?)\]", block)
        if sm:
            for x in re.split(r"[,\s]+", sm.group(1)):
                x = x.strip().strip('"').strip("'")
                if x:
                    referenced_ids.add(x[:8])

    if not referenced_ids:
        print(f"[insight-forge] Entry {entry_id} not found or has no sessions", file=sys.stderr)
        return metas, sessions  # render all

    kept_metas, kept_sessions = [], []
    for m, evs in zip(metas, sessions):
        sid = m.get("session_short", "")[:8]
        if sid in referenced_ids:
            kept_metas.append(m)
            kept_sessions.append(evs)
    return kept_metas, kept_sessions


def main():
    p = argparse.ArgumentParser(description="Render iMessage-style HTML evidence annex.")
    p.add_argument("--forge-dir", type=str, default=".insight-forge")
    p.add_argument("--input", type=str, default=None,
                   help="normalized.jsonl path (default: .insight-forge/.cache/normalized.jsonl)")
    p.add_argument("--entry", type=str, default=None,
                   help="Filter to sessions referenced by this entry ID (e.g., C03)")
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--template", type=str, default=str(TEMPLATE_PATH_DEFAULT))
    args = p.parse_args()

    forge_dir = Path(args.forge_dir)
    input_path = Path(args.input) if args.input else (forge_dir / ".cache" / "normalized.jsonl")
    if not input_path.exists():
        print(f"[insight-forge] No normalized input at {input_path}", file=sys.stderr)
        print(f"[insight-forge] Run extract_*.py first and pipe to {input_path}", file=sys.stderr)
        sys.exit(1)

    template_path = Path(args.template)
    if not template_path.exists():
        print(f"[insight-forge] Template not found at {template_path}", file=sys.stderr)
        sys.exit(1)
    template = template_path.read_text(encoding="utf-8")

    metas, sessions = load_normalized(input_path)
    if args.entry:
        metas, sessions = filter_by_entry(forge_dir, args.entry, metas, sessions)

    body_parts = []
    for meta, events in zip(metas, sessions):
        body_parts.append(render_session(meta, events))
    body = "\n".join(body_parts) if body_parts else "<p style='text-align:center;color:#888'>No sessions to render.</p>"

    title = "Session Evidence"
    if args.entry:
        title = f"Evidence for {args.entry}"
    subtitle = f"{len(metas)} session(s) — generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}"

    rendered = template.replace("{{TITLE}}", html.escape(title)) \
                       .replace("{{SUBTITLE}}", html.escape(subtitle)) \
                       .replace("{{BODY}}", body)

    out_path = Path(args.out) if args.out else (
        forge_dir / "evidence" / (f"sessions-{args.entry}.html" if args.entry else "sessions.html")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"[insight-forge] Evidence rendered to {out_path}", file=sys.stderr)
    print(out_path)


if __name__ == "__main__":
    main()
