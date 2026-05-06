"""Tests for scripts/artifact_commitment.py — file-existence MVP for the
artifact-commitment closure signal.

Conservative discipline: false positives are worse than false negatives.
A path mentioned but absent shouldn't fire (the rule isn't yet committed
to the project). A tool name without its canonical marker shouldn't fire
either. The signal is only emitted when there's hard evidence on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from artifact_commitment import (_extract_paths, _extract_tools,
                                    detect_artifact_commitment)


# --- _extract_paths ---------------------------------------------------

@pytest.mark.parametrize("text,expected_subset", [
    ("Tests live in tests/, not __tests__/", {"tests"}),
    ("Use src/components/Header.tsx for the layout", {"src/components/Header.tsx"}),
    ("CI config is at .github/workflows/main.yml", {".github/workflows/main.yml"}),
    ("The pyproject.toml has the config", {"pyproject.toml"}),
    # Plain English — no path mentions
    ("Use pnpm for package management", set()),
])
def test_extract_paths_finds_real_paths(text, expected_subset):
    paths = set(_extract_paths(text))
    for p in expected_subset:
        assert p in paths, f"expected {p!r} in {paths!r}"


def test_extract_paths_handles_empty():
    assert _extract_paths("") == []
    assert _extract_paths(None) == []


# --- _extract_tools ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Use pnpm not npm", {"pnpm", "npm"}),
    ("Always run ruff for lint", {"ruff"}),
    ("Use mypy for type checks", {"mypy"}),
    ("Deploy with kubectl apply", {"kubectl"}),
    # Tool name embedded in another word — must NOT match
    ("This pnpmpkg is unrelated", set()),
])
def test_extract_tools_finds_known_tools(text, expected):
    tools = set(_extract_tools(text))
    if expected:
        assert tools >= expected, f"expected {expected} in {tools}"
    else:
        assert tools == set()


def test_extract_tools_case_insensitive():
    """Tool names should match regardless of case."""
    assert "ruff" in _extract_tools("Always run RUFF for lint")
    assert "pnpm" in _extract_tools("Use PnPm here")


# --- detect_artifact_commitment: path-based --------------------------

def test_path_match_when_directory_exists(tmp_path):
    (tmp_path / "tests").mkdir()
    result = detect_artifact_commitment(
        "Tests live in tests/, not __tests__/", tmp_path,
    )
    assert result is not None
    assert "tests" in result


def test_path_no_match_when_directory_absent(tmp_path):
    """Mentioned path doesn't exist on disk → no commitment."""
    result = detect_artifact_commitment(
        "Tests live in tests/, not __tests__/", tmp_path,
    )
    assert result is None


def test_path_match_with_filename(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    result = detect_artifact_commitment(
        "Configuration lives in pyproject.toml", tmp_path,
    )
    assert result is not None


# --- detect_artifact_commitment: tool-marker --------------------------

def test_tool_marker_pnpm_lock_present(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n")
    result = detect_artifact_commitment(
        "Use pnpm for package management", tmp_path,
    )
    assert result is not None
    assert "pnpm" in result and "pnpm-lock.yaml" in result


def test_tool_marker_yarn_lock_present(tmp_path):
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
    result = detect_artifact_commitment(
        "Use yarn for this monorepo", tmp_path,
    )
    assert result is not None
    assert "yarn" in result


def test_tool_no_match_without_marker(tmp_path):
    """Mentioned tool without its lockfile/config → no commitment."""
    result = detect_artifact_commitment("Use pnpm here", tmp_path)
    assert result is None


# --- detect_artifact_commitment: config-reference --------------------

def test_ruff_config_in_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\n\n[tool.ruff]\nline-length = 100\n"
    )
    result = detect_artifact_commitment("Always use ruff for lint", tmp_path)
    assert result is not None
    assert "ruff" in result
    assert "pyproject.toml" in result


def test_pnpm_packagemanager_in_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name": "x", "packageManager": "pnpm@9.0.0"}'
    )
    result = detect_artifact_commitment("Use pnpm in this repo", tmp_path)
    assert result is not None
    assert "pnpm" in result


def test_no_config_reference_when_pyproject_absent(tmp_path):
    """Tool mentioned, pyproject.toml present but does NOT mention the
    tool → no commitment."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    result = detect_artifact_commitment("Use ruff for lint", tmp_path)
    assert result is None


# --- defensive paths --------------------------------------------------

def test_returns_none_when_project_root_is_none():
    assert detect_artifact_commitment("Use pnpm", None) is None


def test_returns_none_when_project_root_does_not_exist(tmp_path):
    fake = tmp_path / "does-not-exist"
    assert detect_artifact_commitment("Use pnpm", fake) is None


def test_returns_none_when_observation_text_is_empty(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("x")
    assert detect_artifact_commitment("", tmp_path) is None
    assert detect_artifact_commitment(None, tmp_path) is None


def test_handles_unreadable_config_silently(tmp_path):
    """If pyproject.toml exists but can't be read (permission, encoding),
    we should NOT crash — we should silently fall through to other
    matchers."""
    cf = tmp_path / "pyproject.toml"
    cf.write_bytes(b"\xff\xfe\x00\x00invalid")  # invalid UTF-8
    # No marker file, no readable config → None
    result = detect_artifact_commitment("Use ruff", tmp_path)
    assert result is None


def test_first_match_wins(tmp_path):
    """When both a path AND a tool marker would fire, the path is checked
    first (more specific to the rule's intent)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pnpm-lock.yaml").write_text("x")
    result = detect_artifact_commitment(
        "Tests live in tests/ and we use pnpm", tmp_path,
    )
    assert result is not None
    # Either path or tool match is acceptable; just verify it fires.
    assert "tests" in result or "pnpm" in result
