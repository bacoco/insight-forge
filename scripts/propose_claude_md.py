#!/usr/bin/env python3
"""
Insight Forge — propose CLAUDE.md / AGENTS.md updates from cristallized knowledge.

Reads the cristallized layers under .insight-forge/logic/ and generates a markdown
proposal for the user to review and apply manually. NEVER auto-edits the target
file — only writes to .insight-forge/proposals/<date>.md.

USAGE:
    python3 propose_claude_md.py [--forge-dir .insight-forge] [--target CLAUDE.md|AGENTS.md]
                                 [--since YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_md_entries(text: str, prefix: str) -> list[dict]:
    """Parse entries of the form '## <prefix>NN: ...\\n- **Field**: value\\n...'"""
    entries = []
    # Split on '## <prefix>'
    chunks = re.split(rf"^## ({prefix}\d+):", text, flags=re.MULTILINE)
    # chunks[0] is preamble, then alternating id/body
    for i in range(1, len(chunks), 2):
        eid = chunks[i].strip()
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        # First line = title (after the colon on the H2 line, but split consumed it)
        # The body starts right after the colon — split into title and the rest
        first_break = body.find("\n")
        title = body[:first_break].strip() if first_break >= 0 else body.strip()
        rest = body[first_break + 1:] if first_break >= 0 else ""
        # Parse `- **Field**: value` lines
        fields = {}
        for line in rest.split("\n"):
            m = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*:\s*(.*)$", line)
            if m:
                fields[m.group(1).strip()] = m.group(2).strip()
        entries.append({"id": eid, "title": title, **fields})
    return entries


def detect_target_file(forge_dir: Path, override: str = None) -> tuple[str, str]:
    """Decide between CLAUDE.md and AGENTS.md.
    Returns (filename, agent_name)."""
    if override:
        return override, ("claude" if "CLAUDE" in override.upper() else "codex")

    project_root = forge_dir.parent
    has_claude = (project_root / "CLAUDE.md").exists()
    has_agents = (project_root / "AGENTS.md").exists()

    if has_claude and not has_agents:
        return "CLAUDE.md", "claude"
    if has_agents and not has_claude:
        return "AGENTS.md", "codex"
    if has_claude and has_agents:
        # Both exist — write a unified proposal targeting both
        return "BOTH", "both"
    # Neither exists — default to CLAUDE.md (we'll suggest creating it)
    return "CLAUDE.md", "claude"


def filter_recent(entries: list[dict], since: datetime, sessions_index_path: Path) -> list[dict]:
    """Keep only entries whose contributing sessions are newer than `since`."""
    # If no session_index, keep all
    if not sessions_index_path.exists():
        return entries
    try:
        idx_text = sessions_index_path.read_text(encoding="utf-8")
    except Exception:
        return entries

    recent_session_ids = set()
    for line in idx_text.split("\n"):
        m = re.search(r"^\s*-\s*id:\s*(\S+)", line)
        if m:
            current_id = m.group(1).strip().strip('"')
        m_date = re.search(r"^\s*date:\s*(\S+)", line)
        if m_date and current_id:
            try:
                d = datetime.fromisoformat(m_date.group(1).strip().strip('"'))
                if d.replace(tzinfo=timezone.utc) >= since:
                    recent_session_ids.add(current_id)
            except Exception:
                pass

    if not recent_session_ids:
        return entries  # No filter possible

    kept = []
    for e in entries:
        sessions_field = e.get("Sessions", "")
        # Format is typically "[id1, id2]" — extract IDs
        ids = re.findall(r"[a-f0-9]{4,}", sessions_field)
        if any(i in " ".join(recent_session_ids) for i in ids):
            kept.append(e)
    return kept


def build_proposal(forge_dir: Path, target: str, agent_name: str,
                    since: datetime = None) -> str:
    """Compose the proposal markdown."""
    logic = forge_dir / "logic"
    claims = parse_md_entries((logic / "claims.md").read_text(encoding="utf-8"), "C") if (logic / "claims.md").exists() else []
    heuristics = parse_md_entries((logic / "heuristics.md").read_text(encoding="utf-8"), "H") if (logic / "heuristics.md").exists() else []
    dead_ends = parse_md_entries((logic / "dead_ends.md").read_text(encoding="utf-8"), "D") if (logic / "dead_ends.md").exists() else []

    if since:
        sidx = forge_dir / "trace" / "session_index.yaml"
        claims = filter_recent(claims, since, sidx)
        heuristics = filter_recent(heuristics, since, sidx)
        dead_ends = filter_recent(dead_ends, since, sidx)

    today = datetime.now(timezone.utc).date().isoformat()
    target_label = target if target != "BOTH" else "CLAUDE.md and AGENTS.md"

    out = []
    out.append(f"# Insight Forge — Proposed updates for {target_label}\n")
    out.append(f"Run: {today}\n")
    out.append("**This is a proposal.** Insight Forge never auto-edits these files. ")
    out.append("Review each suggestion below; copy what you want into the target file manually.\n\n")

    out.append("---\n\n")
    out.append("## Suggested additions\n\n")

    if heuristics:
        out.append("### Heuristics (project rules)\n\n")
        for h in heuristics:
            rule = h.get("Rule", h.get("title", ""))
            counter = h.get("Counter-cases", "not_explored")
            sessions = h.get("Sessions", "[]")
            out.append(f"- **{h['id']}**: {rule}\n")
            if counter and counter != "not_explored":
                out.append(f"  - *Caveat*: {counter}\n")
            out.append(f"  - *Sessions*: {sessions}\n\n")

    if claims:
        out.append("### Claims (project facts)\n\n")
        for c in claims:
            stmt = c.get("Statement", c.get("title", ""))
            status = c.get("Status", "hypothesis")
            counter = c.get("Counter-evidence", "not_explored")
            sessions = c.get("Sessions", "[]")
            out.append(f"- **{c['id']}** *({status})*: {stmt}\n")
            if counter and counter != "not_explored":
                out.append(f"  - *Counter-evidence*: {counter}\n")
            out.append(f"  - *Sessions*: {sessions}\n\n")

    if dead_ends:
        out.append("### Dead ends (avoid)\n\n")
        for d in dead_ends:
            avoid = d.get("Avoid signal", d.get("title", ""))
            lesson = d.get("Lesson", "")
            could = d.get("Could have worked if", "")
            sessions = d.get("Sessions", "[]")
            out.append(f"- **{d['id']}**: avoid {avoid}\n")
            if lesson:
                out.append(f"  - *Lesson*: {lesson}\n")
            if could and could != "not_explored":
                out.append(f"  - *Could have worked if*: {could}\n")
            out.append(f"  - *Sessions*: {sessions}\n\n")

    if not (heuristics or claims or dead_ends):
        out.append("_No cristallized knowledge yet — re-run after more sessions or after `--challenge`._\n\n")

    out.append("---\n\n")
    out.append("## Suggested copy-paste snippets\n\n")
    out.append(f"You can paste these blocks under existing `{target_label}` sections (or create them).\n\n")

    if heuristics:
        out.append("**Under `## Project conventions` or similar:**\n\n```markdown\n")
        for h in heuristics:
            rule = h.get("Rule", h.get("title", ""))
            out.append(f"- {rule}\n")
        out.append("```\n\n")

    if dead_ends:
        out.append("**Under `## Avoid` or `## Known dead ends`:**\n\n```markdown\n")
        for d in dead_ends:
            avoid = d.get("Avoid signal", d.get("title", ""))
            lesson = d.get("Lesson", "")
            out.append(f"- Avoid: {avoid}")
            if lesson:
                out.append(f" — {lesson}")
            out.append("\n")
        out.append("```\n\n")

    out.append("---\n\n")
    out.append("## Provenance & Devil's Advocate notes\n\n")
    out.append("Each suggestion is backed by:\n")
    out.append("- A specific cristallized entry (see `.insight-forge/logic/`) with its closure signal\n")
    out.append("- One or more session IDs in `.insight-forge/trace/session_index.yaml`\n")
    out.append("- A `Counter-evidence` clause (Devil's Advocate). Where it says `not_explored`, ")
    out.append("the suggestion is more speculative — review carefully.\n\n")

    return "".join(out)


def main():
    p = argparse.ArgumentParser(description="Propose CLAUDE.md / AGENTS.md updates from insight-forge state.")
    p.add_argument("--forge-dir", type=str, default=".insight-forge")
    p.add_argument("--target", type=str, default=None,
                   help="Override target file: CLAUDE.md or AGENTS.md.")
    p.add_argument("--since", type=str, default=None,
                   help="Only include knowledge from sessions on or after this date (YYYY-MM-DD).")
    p.add_argument("--out", type=str, default=None,
                   help="Output path (default: .insight-forge/proposals/<date>.md).")
    args = p.parse_args()

    forge_dir = Path(args.forge_dir)
    if not forge_dir.exists():
        print(f"[insight-forge] Forge dir not found: {forge_dir}", file=sys.stderr)
        sys.exit(1)

    target, agent_name = detect_target_file(forge_dir, args.target)

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    proposal = build_proposal(forge_dir, target, agent_name, since)

    out_path = Path(args.out) if args.out else (
        forge_dir / "proposals" / f"{datetime.now(timezone.utc).date().isoformat()}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proposal, encoding="utf-8")
    print(f"[insight-forge] Proposal written to {out_path}", file=sys.stderr)
    print(out_path)


if __name__ == "__main__":
    main()
