"""Tests for scripts/propose_claude_md.py.

Currently focused on filter_recent() — issue #30 surfaced an
UnboundLocalError when a `date:` line appears before any `- id:` line in
trace/session_index.yaml. PyYAML's safe_dump can produce that ordering, so
the function has to handle it.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from propose_claude_md import filter_recent


# A claim entry shaped exactly like parse_md_entries() output so we can
# exercise the keep/drop logic for real.
_ENTRY = {
    "id": "C01",
    "title": "the claim title",
    "Sessions": "[abcd1234]",
}


def _write_session_index(tmp_path: Path, content: str) -> Path:
    """Write a session_index.yaml fixture and return its Path."""
    p = tmp_path / "session_index.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_filter_recent_returns_all_when_index_missing(tmp_path):
    sidx = tmp_path / "does_not_exist.yaml"
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_keeps_recent_session(tmp_path):
    sidx = _write_session_index(tmp_path, """
        sessions:
          - id: abcd1234
            date: 2026-05-01
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_drops_old_session(tmp_path):
    """Entries whose session is OLDER than `since` AND no recent ID matches
    are filtered out. The function returns all entries when no recent IDs
    are found at all (so the filter is "additive narrow", not "drop all")."""
    sidx = _write_session_index(tmp_path, """
        sessions:
          - id: efef5678
            date: 2026-01-01
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    # No recent IDs → returns entries unchanged ("no filter possible").
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_handles_date_before_id(tmp_path):
    """Issue #30 regression. PyYAML's safe_dump (which pipeline.py uses
    for trace/session_index.yaml) sorts mapping keys alphabetically by
    default, so 'agent' comes first inside each list item, then 'date',
    then 'full_id', then 'id'. The `- id:` regex misses the leading line
    (the `-` lands on `agent:`), and the `date:` line is reached *before*
    any line sets current_id — the pre-fix code raised UnboundLocalError.

    This fixture reproduces the exact YAML shape pipeline.py writes in
    production, with no manual reordering."""
    sidx = _write_session_index(tmp_path, """
        sessions:
        - agent: claude
          date: 2026-05-01
          full_id: abcd1234-0000-0000-0000-000000000001
          id: abcd1234
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    # Must NOT raise UnboundLocalError. The function should still match
    # the recent session via the `id:` line that comes later.
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_handles_date_with_no_session_at_all(tmp_path):
    """A genuinely malformed file with a stray `date:` and no `- id:` lines
    must not crash."""
    sidx = _write_session_index(tmp_path, """
        misc:
          date: 2026-05-01
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    # Must NOT raise UnboundLocalError.
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_handles_quoted_iso_date(tmp_path):
    """A date stored with surrounding quotes (PyYAML often does this)
    must round-trip through fromisoformat after stripping."""
    sidx = _write_session_index(tmp_path, """
        sessions:
          - id: abcd1234
            date: "2026-05-01"
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = filter_recent([_ENTRY], since, sidx)
    assert result == [_ENTRY]


def test_filter_recent_handles_unparseable_date_silently(tmp_path):
    """A date that can't parse should not crash the whole proposal — just
    skip that session's contribution."""
    sidx = _write_session_index(tmp_path, """
        sessions:
          - id: abcd1234
            date: not-a-real-date
        """)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = filter_recent([_ENTRY], since, sidx)
    # No usable recent IDs → entries returned unchanged.
    assert result == [_ENTRY]
