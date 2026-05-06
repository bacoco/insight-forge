"""Integration test: artifact-commitment closure signal fires through the
full pipeline when a project root has on-disk evidence for a staged
observation.

The fixture used here is a bare assistant claim about pnpm — no verbal
affirmation in the same session, no tool result, only one session so
no topic-abandonment is possible. Without artifact-commitment, the
observation would stay in staging. With a `pnpm-lock.yaml` present in
the project root, it should crystallize via artifact-commitment.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_fixture(path: Path) -> None:
    """A minimal session that stages a claim about pnpm without any
    closure signal. Without artifact-commitment, this stays in staging."""
    path.write_text(textwrap.dedent("""\
        {"_marker": "session_start", "session_id": "art00001-0000-0000-0000-000000000001", "session_short": "art00001", "agent": "claude", "mtime": "2026-05-04T10:00:00", "size_kb": 2}
        {"role": "assistant", "content": "pnpm is faster than npm because of its content-addressable store, when caching is hot.", "timestamp": "2026-05-04T10:00:05", "session_id": "art00001-0000-0000-0000-000000000001", "session_short": "art00001", "agent": "claude"}
        {"role": "user", "content": "ok cool, let's continue with the deploy", "timestamp": "2026-05-04T10:00:10", "session_id": "art00001-0000-0000-0000-000000000001", "session_short": "art00001", "agent": "claude"}
        {"_marker": "session_end"}
    """), encoding="utf-8")


def _run_pipeline(fixture: Path, forge_dir: Path) -> dict:
    """Run pipeline.py and return the parsed JSON summary."""
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "pipeline.py"),
          "--input", str(fixture), "--forge-dir", str(forge_dir)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, f"pipeline failed: {res.stderr}"
    # pipeline.py writes status to stderr and the JSON summary to stdout
    return json.loads(res.stdout)


def test_artifact_commitment_does_not_fire_without_marker(tmp_path):
    """Same fixture, NO pnpm-lock.yaml in project root → no crystallization
    via artifact-commitment. Observation stays in staging."""
    fixture = tmp_path / "f.jsonl"
    _write_fixture(fixture)
    project_root = tmp_path
    forge_dir = project_root / ".insight-forge"

    summary = _run_pipeline(fixture, forge_dir)

    # No closure signal fires → 0 crystallized, 1 staged.
    assert summary["crystallized"] == 0
    assert summary["staged"] >= 1


def test_artifact_commitment_fires_when_lockfile_exists(tmp_path):
    """Same fixture, but pnpm-lock.yaml present in project root → the
    staged claim about pnpm crystallizes via artifact-commitment."""
    fixture = tmp_path / "f.jsonl"
    _write_fixture(fixture)
    project_root = tmp_path
    forge_dir = project_root / ".insight-forge"

    # Plant the artifact BEFORE running the pipeline.
    (project_root / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n")

    summary = _run_pipeline(fixture, forge_dir)

    assert summary["crystallized"] >= 1, (
        "Expected at least one crystallization via artifact-commitment.\n"
        f"Got summary: {summary}"
    )

    # Verify the bundle records the right closure signal.
    bundles_dir = forge_dir / "evidence" / "bundles"
    bundle_files = [b for b in bundles_dir.glob("*.yaml") if b.name != "README.md"]
    assert bundle_files, "no evidence bundle written"

    text = bundle_files[0].read_text(encoding="utf-8")
    assert "crystallized_via" in text
    assert "artifact-commitment" in text


def test_artifact_commitment_silent_when_project_root_missing(tmp_path):
    """When pipeline.py runs with a forge_dir whose parent doesn't contain
    a real project, artifact-commitment must not crash and must simply
    return None — preserving the existing observation flow."""
    fixture = tmp_path / "f.jsonl"
    _write_fixture(fixture)
    # Use a forge_dir whose parent is a fresh empty tmp dir
    forge_dir = tmp_path / "deeply" / "nested" / ".insight-forge"

    summary = _run_pipeline(fixture, forge_dir)

    # No crash, no crystallization, observation stays staged.
    assert summary["crystallized"] == 0
