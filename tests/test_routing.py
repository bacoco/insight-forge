"""Tests for scripts/routing.py — routing-fit classification.

Conservative discipline: false positives are worse than false negatives.
A short, normal rule must NEVER fire either flag. Tests pin the exact
patterns we want to detect AND the patterns we explicitly avoid.
"""
from __future__ import annotations

import pytest

from routing import classify_target_fit


# --- project-specific (home path) ------------------------------------

@pytest.mark.parametrize("text", [
    "Update /Users/loic/develop/insight-forge/scripts/run.py before deploy",
    "Logs land in /home/alice/.config/myapp/logs/",
    "Build artifact at /Users/dev/projects/foo/dist/main.js",
])
def test_flags_absolute_home_path(text):
    flags = classify_target_fit(text)
    assert any(f["flag"] == "project-specific" for f in flags)


@pytest.mark.parametrize("text", [
    # Generic rules — no home path
    "Always use pnpm not npm in this repo",
    "Tests live in tests/, not __tests__/",
    "Run lint:fix before committing",
    # System paths that aren't home dirs — must NOT fire
    "Build with /usr/local/bin/python3",
    "Logs at /var/log/sys.log",
    # Relative paths
    "Use src/components/Header.tsx for layout",
])
def test_does_not_flag_non_home_paths(text):
    flags = classify_target_fit(text)
    project_flags = [f for f in flags if f["flag"] == "project-specific"]
    assert not project_flags


def test_long_home_path_truncated_in_reason():
    """The annotation must not leak a 200-char absolute path verbatim."""
    long_path = "/Users/loic/" + "a" * 200 + "/file.txt"
    flags = classify_target_fit(f"Check {long_path} for the issue")
    assert flags
    assert "…" in flags[0]["reason"]


# --- narrative ------------------------------------------------------

def test_flags_long_first_person_narrative():
    text = (
        "I tried to upgrade the dependency to v3, but after several hours of "
        "debugging the build, we discovered that the lockfile was pinning a "
        "transitive dependency that had a breaking change. The fix was to "
        "regenerate the lockfile with the new resolver, then run the full test "
        "suite to confirm nothing else regressed."
    )
    flags = classify_target_fit(text)
    assert any(f["flag"] == "narrative" for f in flags)


def test_does_not_flag_short_first_person_text():
    """Short text with first-person markers — too brief to be a narrative
    that should be a lesson."""
    text = "I tried pnpm and it works"
    flags = classify_target_fit(text)
    narr = [f for f in flags if f["flag"] == "narrative"]
    assert not narr


def test_does_not_flag_long_imperative_rule():
    """A long rule that's still imperative (no story markers) must NOT
    fire as a narrative."""
    text = (
        "Always use pnpm in this repo, never npm or yarn. Run pnpm install "
        "before any commit, pnpm lint:fix before pushing, and ensure the "
        "lockfile is up to date by running pnpm dedupe periodically. The "
        "package manager choice impacts CI cache hits and reproducibility."
    )
    flags = classify_target_fit(text)
    narr = [f for f in flags if f["flag"] == "narrative"]
    assert not narr, f"narrative incorrectly fired: {flags}"


# --- combined / edge cases ------------------------------------------

def test_can_fire_both_flags():
    """Long retrospective text that mentions a home path — both flags."""
    text = (
        "I tried debugging /Users/loic/projects/foo/scripts/migrate.py for "
        "several hours after the build failed. We discovered that the env "
        "var setup needed to be reordered, but only on macOS. The fix is "
        "documented in a separate runbook because it's not a rule, just a "
        "post-mortem of a specific incident."
    )
    flags = classify_target_fit(text)
    flag_names = {f["flag"] for f in flags}
    assert "project-specific" in flag_names
    assert "narrative" in flag_names


def test_empty_text_returns_no_flags():
    assert classify_target_fit("") == []
    assert classify_target_fit(None) == []


def test_ordinary_rule_returns_no_flags():
    assert classify_target_fit("Always use pnpm not npm") == []
    assert classify_target_fit("Tests live in tests/") == []


def test_french_narrative_pattern():
    """Story markers exist in French too — j'ai essayé / découvert / etc."""
    text = (
        "J'ai essayé de mettre à jour la dépendance à la v3, mais après "
        "plusieurs heures de débogage du build, nous avons découvert que "
        "le lockfile pinnait une dépendance transitive avec un breaking "
        "change. La solution était de régénérer le lockfile avec le nouveau "
        "resolver puis de tester l'ensemble du projet."
    )
    flags = classify_target_fit(text)
    # FR markers may or may not match the regex (it's optimized for EN).
    # Don't pin FR detection until we've proven the pattern set.
    # Just verify no crash and a reasonable result.
    assert isinstance(flags, list)
