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


# --- near-duplicate annotation in proposals ----------------------------

import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_pipeline_then_propose(fixture_path: Path, forge_dir: Path) -> str:
    """Run the full pipeline + proposer on a fixture, return proposal text."""
    pipeline = REPO_ROOT / "scripts" / "pipeline.py"
    propose = REPO_ROOT / "scripts" / "propose_claude_md.py"

    res = subprocess.run(
        [sys.executable, str(pipeline),
          "--input", str(fixture_path),
          "--forge-dir", str(forge_dir)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, f"pipeline failed: {res.stderr}"

    res = subprocess.run(
        [sys.executable, str(propose), "--forge-dir", str(forge_dir)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, f"propose failed: {res.stderr}"

    proposal_path = Path(res.stdout.strip())
    return proposal_path.read_text(encoding="utf-8")


def test_proposal_flags_near_duplicate_heuristics(tmp_path):
    """The near_duplicate_heuristic fixture produces two heuristics about
    pnpm vs npm. The proposal should annotate the second one with a
    'Possibly redundant' marker pointing at the first."""
    fixture = REPO_ROOT / "evals" / "fixtures" / "near_duplicate_heuristic.jsonl"
    proposal = _run_pipeline_then_propose(fixture, tmp_path / ".forge")
    assert "⚠ *Possibly redundant*" in proposal, (
        "Proposal did not flag the near-duplicate. Got:\n" + proposal[:2000]
    )


def test_proposal_does_not_flag_unrelated_entries(tmp_path):
    """The simple_success fixture produces exactly one heuristic. There's
    nothing to be redundant with — the proposal must NOT contain a
    'Possibly redundant' annotation."""
    fixture = REPO_ROOT / "evals" / "fixtures" / "simple_success.jsonl"
    proposal = _run_pipeline_then_propose(fixture, tmp_path / ".forge")
    assert "⚠ *Possibly redundant*" not in proposal


def test_proposal_flags_against_existing_claude_md(tmp_path):
    """When a CLAUDE.md sits at the project root with a rule similar to a
    newly-crystallized one, the proposal should call it out so the user
    doesn't paste a duplicate on top of an existing one."""
    fixture = REPO_ROOT / "evals" / "fixtures" / "simple_success.jsonl"
    forge_dir = tmp_path / ".insight-forge"
    project_root = tmp_path  # project root = parent of forge_dir
    (project_root / "CLAUDE.md").write_text(
        "# Project rules\n\n"
        "- Always use pnpm in this repo, never use npm.\n",
        encoding="utf-8",
    )
    proposal = _run_pipeline_then_propose(fixture, forge_dir)
    assert "⚠ *Already in your" in proposal, (
        "Proposal did not flag the existing CLAUDE.md line. Got:\n"
        + proposal[:2000]
    )
