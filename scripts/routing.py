"""
Insight Forge — routing-fit classification for proposed entries.

Surfaces flags when a crystallized entry looks like it belongs somewhere
other than a CLAUDE.md / AGENTS.md rule list. The classifier does NOT
route — it just suggests, same conservative pattern as the rest of the
proposal flow.

Two narrow signals shipped today:

  - **project-specific** — the entry contains content that's tied to a
    specific machine or person (absolute home directory paths). A rule
    referencing `/Users/loic/something/` should probably not land in a
    `~/.claude/CLAUDE.md` global file.

  - **narrative** — the entry is long discursive text with story
    markers ("I tried…", "we found…"). It reads like a retrospective
    note, not a project rule. The user might prefer to put it in a
    `lessons.md` or `RETROS.md` instead.

The full routing taxonomy from the original brief (wiki / skill / hook /
lessons) is intentionally NOT shipped — those destinations don't exist
as conventions across projects, so committing to them is premature.
This module only flags ambiguity; it never names a target.
"""
from __future__ import annotations

import re

# A leading-dot-or-letter path under /Users/<name>/ or /home/<name>/.
# Strict: must have at least one path segment after the username so
# `/Users/loic` alone (rare in rule text) doesn't fire.
_HOME_PATH_RE = re.compile(
    r"/(?:Users|home)/[a-zA-Z][a-zA-Z0-9_\-.]+/[\w\-./]+",
)

# First-person retrospective markers. Matched case-insensitive.
_NARRATIVE_RE = re.compile(
    r"\b("
    r"i\s+(?:tried|noticed|discovered|spent|debugged|realized|figured|found|"
    r"     thought|expected|wondered|realised)"
    r"|we\s+(?:tried|noticed|discovered|spent|debugged|realized|found|"
    r"      figured|realised)"
    r"|after\s+(?:hours|days|weeks|months|debugging|trying)"
    r"|j['ae']\s+(?:ai|ai\s+essayé|ai\s+remarqué|ai\s+découvert)"
    r")\b",
    re.IGNORECASE | re.VERBOSE,
)

# Length above which we'll consider an entry as candidate-narrative.
# Most one-sentence rules are well under 200 chars; lessons that fit
# the "story" pattern almost always exceed it.
_NARRATIVE_MIN_CHARS = 200


def classify_target_fit(text: str) -> list[dict]:
    """Return zero or more {flag, reason} dicts describing routing-fit
    issues with `text`. Empty list when the entry looks like a
    well-formed project rule.

    Both signals are independent — an entry can fire both flags (e.g.
    a long retrospective that mentions a home path).
    """
    if not text:
        return []
    flags: list[dict] = []

    home_match = _HOME_PATH_RE.search(text)
    if home_match:
        # Truncate the matched path for display so users see what fired
        # without leaking long absolute paths in the proposal markdown.
        sample = home_match.group(0)
        if len(sample) > 60:
            sample = sample[:57] + "…"
        flags.append({
            "flag": "project-specific",
            "reason": f"contains an absolute home path ({sample}) — "
                       f"should probably not go in a shared/global file",
        })

    if len(text) >= _NARRATIVE_MIN_CHARS and _NARRATIVE_RE.search(text):
        flags.append({
            "flag": "narrative",
            "reason": "long text with first-person story markers — "
                       "looks more like a lesson/retrospective than a rule",
        })

    return flags
