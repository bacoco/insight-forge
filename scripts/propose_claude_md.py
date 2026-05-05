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

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def _load_bundle(forge_dir: Path, entry_id: str) -> dict:
    """Load the structured evidence bundle for an entry, or {} if missing."""
    p = forge_dir / "evidence" / "bundles" / f"{entry_id}.yaml"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if _HAS_YAML:
        try:
            return _yaml.safe_load(text) or {}
        except Exception:
            return {}
    # Fallback to the lite parser
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline import yaml_load_simple  # noqa: E402
        return yaml_load_simple(text) or {}
    except Exception:
        return {}


def _format_quote(ev: dict) -> str:
    """One-line markdown bullet describing an evidence event."""
    quote = (ev.get("quote") or "").strip()
    if len(quote) > 220:
        quote = quote[:217] + "…"
    quote = quote.replace("\n", " ")
    ts = (ev.get("timestamp") or "")[:10]  # date only
    role = ev.get("role") or ""
    kind = ev.get("kind") or ""
    label = {
        "trigger": "*You said*" if role == "user" else "*Claude said*",
        "verbal-affirmation": "*You confirmed*",
        "empirical-resolution": "*Tool result*",
        "topic-abandonment": "*Then untouched in subsequent sessions*",
    }.get(kind, "*Evidence*")
    when = f" ({ts})" if ts else ""
    if kind == "topic-abandonment":
        return f"  - {label}\n"
    if not quote:
        return f"  - {label}{when}\n"
    return f"  - {label}{when}: \"{quote}\"\n"


def _bundle_quotes(forge_dir: Path, entry_id: str) -> str:
    """Render the trigger + closure quotes for an entry, ready to splice."""
    bundle = _load_bundle(forge_dir, entry_id)
    evidence = bundle.get("evidence") or []
    if not evidence:
        return ""
    chunks = [_format_quote(ev) for ev in evidence]
    return "".join(chunks)


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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            out.append(_bundle_quotes(forge_dir, h["id"]))
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
            out.append(_bundle_quotes(forge_dir, c["id"]))
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
            out.append(_bundle_quotes(forge_dir, d["id"]))
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
    p.add_argument("--redact", action="store_true",
                   help="Replace likely secrets (AWS/GitHub/OpenAI/Anthropic keys, "
                        "JWTs, auth headers, URLs with credentials, password key=value, "
                        "emails, home directory paths) with <REDACTED:type> markers. "
                        "Use this before sharing a proposal with someone else.")
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

    # Privacy: scan the rendered proposal for likely secrets. Always warn the
    # user via a header block when found; redact in-place only when --redact
    # is passed. The default keeps the source quotes intact (the user may
    # need to see the actual content) but the warning ensures they don't
    # paste blindly.
    proposal = _apply_secret_policy(proposal, redact_in_place=args.redact)

    out_path = Path(args.out) if args.out else (
        forge_dir / "proposals" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proposal, encoding="utf-8")

    # Friendly human-readable summary on stderr — what the user actually wants
    # to see. The stdout contract (`out_path`) is preserved for run.py.
    _print_summary(forge_dir, out_path, target, since)
    print(out_path)


def _apply_secret_policy(proposal: str, redact_in_place: bool) -> str:
    """Scan the proposal for secrets, warn at the top if found, optionally
    redact the secrets in-place."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from redact import find_secrets, redact, secrets_summary  # noqa: E402

    matches = find_secrets(proposal)
    if not matches:
        return proposal

    summary = secrets_summary(proposal)
    if redact_in_place:
        proposal = redact(proposal, mode="tag")
        warning = (
            f"> ⚠ **Secrets detected and redacted.** This proposal contained "
            f"text matching: {summary}. Each match has been replaced with "
            f"`<REDACTED:type>`. Review the underlying transcripts (or rerun "
            f"without `--redact`) if you need the originals.\n\n"
        )
    else:
        warning = (
            f"> ⚠ **This proposal contains text that looks like potential "
            f"secrets.** Detected: {summary}. The values are kept verbatim so "
            f"you can verify them, but do not paste blindly into "
            f"`CLAUDE.md` / `AGENTS.md`. Re-run with `--redact` to replace "
            f"each match with a `<REDACTED:type>` marker.\n\n"
        )

    # Print to stderr too so the friendly summary surfaces it without the
    # user having to open the proposal file.
    print(f"\n  ⚠ secrets detected in proposal: {summary}", file=sys.stderr)
    if not redact_in_place:
        print(f"    re-run with --redact to replace them with placeholders\n",
              file=sys.stderr)

    # Inject the warning right after the H1 title.
    if proposal.startswith("# "):
        nl = proposal.find("\n")
        head = proposal[:nl + 1]
        rest = proposal[nl + 1:]
        return head + "\n" + warning + rest
    return warning + proposal


def _print_summary(forge_dir: Path, out_path: Path, target: str, since) -> None:
    """Multi-line friendly digest of what was learned."""
    logic = forge_dir / "logic"
    h = parse_md_entries((logic / "heuristics.md").read_text(encoding="utf-8"), "H") \
        if (logic / "heuristics.md").exists() else []
    c = parse_md_entries((logic / "claims.md").read_text(encoding="utf-8"), "C") \
        if (logic / "claims.md").exists() else []
    d = parse_md_entries((logic / "dead_ends.md").read_text(encoding="utf-8"), "D") \
        if (logic / "dead_ends.md").exists() else []

    if since:
        sidx = forge_dir / "trace" / "session_index.yaml"
        h = filter_recent(h, since, sidx)
        c = filter_recent(c, since, sidx)
        d = filter_recent(d, since, sidx)

    # Count staged observations not yet promoted (from staging YAML)
    staged_pending = 0
    obs_path = forge_dir / "staging" / "observations.yaml"
    if obs_path.exists():
        try:
            text = obs_path.read_text(encoding="utf-8")
            data = (_yaml.safe_load(text) if _HAS_YAML else None) or {}
            staged_pending = sum(1 for o in (data.get("observations") or [])
                                 if not o.get("promoted") and not o.get("stale"))
        except Exception:
            pass

    target_label = target if target != "BOTH" else "CLAUDE.md & AGENTS.md"

    sys.stderr.write("\n")
    sys.stderr.write(f"  Insight Forge — proposal for {target_label}\n")
    sys.stderr.write("  " + "─" * 56 + "\n")
    if not (h or c or d):
        sys.stderr.write("  Nothing new crystallized yet — the pipeline saw your\n")
        sys.stderr.write("  sessions but no observation has hit a closure signal.\n")
        sys.stderr.write("  Use the project a bit more, then re-run.\n")
    else:
        if h:
            sys.stderr.write(f"  ✓ {len(h)} project rule{'s' if len(h) != 1 else ''} ready\n")
            for entry in h[:3]:
                rule = entry.get("Rule", entry.get("title", ""))[:80]
                sys.stderr.write(f"      • {rule}\n")
            if len(h) > 3:
                sys.stderr.write(f"      … and {len(h) - 3} more\n")
        if d:
            sys.stderr.write(f"  ✗ {len(d)} dead end{'s' if len(d) != 1 else ''} to avoid\n")
            for entry in d[:2]:
                avoid = entry.get("Avoid signal", entry.get("title", ""))[:80]
                sys.stderr.write(f"      • {avoid}\n")
            if len(d) > 2:
                sys.stderr.write(f"      … and {len(d) - 2} more\n")
        if c:
            sys.stderr.write(f"  ? {len(c)} claim{'s' if len(c) != 1 else ''} (project facts)\n")

    if staged_pending:
        sys.stderr.write(f"  · {staged_pending} observation{'s' if staged_pending != 1 else ''} "
                         f"still in staging (need more sessions)\n")

    sys.stderr.write("\n")
    sys.stderr.write(f"  Full proposal — open or paste from:\n")
    sys.stderr.write(f"    {out_path}\n\n")


if __name__ == "__main__":
    main()
