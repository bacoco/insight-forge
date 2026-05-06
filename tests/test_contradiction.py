"""Tests for scripts/contradiction.py — semantic contradiction and
intra-CLAUDE.md self-duplicate detection.

The discipline is the same as for similarity.py: false positives are
worse than false negatives, because a noisy detector trains users to
ignore the warning. Each positive case shipped here matches a realistic
contradiction; each negative case is a known false-positive pattern we
explicitly avoid.
"""
from __future__ import annotations

import pytest

from contradiction import (_polarity, detect_contradiction,
                            find_contradicted_lines, find_self_duplicates)


# --- _polarity --------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Use pnpm in this repo", "positive"),
    ("Always use pnpm", "positive"),
    ("Don't use npm", "negative"),
    ("Never use yarn", "negative"),
    ("Avoid the legacy migration script", "negative"),
    ("Ne pas utiliser npm", "negative"),
    ("Jamais utiliser yarn", "negative"),
    ("", "positive"),  # empty default
])
def test_polarity_classification(text, expected):
    assert _polarity(text) == expected


# --- detect_contradiction --------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Always use pnpm", "Never use pnpm"),
    ("Use pnpm in this repo", "Don't use pnpm in this repo"),
    ("Always run lint:fix before committing", "Never run lint:fix before committing"),
    ("Use ruff for lint", "Avoid ruff for lint"),
])
def test_contradicts_when_polarity_flips_with_overlap(a, b):
    assert detect_contradiction(a, b)
    # Symmetric — order doesn't matter
    assert detect_contradiction(b, a)


@pytest.mark.parametrize("a,b", [
    # Same polarity — not a contradiction even if overlap is high
    ("Use pnpm", "Use yarn"),
    ("Always use pnpm", "Always run lint"),
    # Different polarity but disjoint subjects — definitely not a contradiction
    ("Use pnpm", "Don't deploy on Friday"),
    ("Never use docker", "Always use ruff"),
])
def test_not_contradiction(a, b):
    assert not detect_contradiction(a, b)


def test_low_overlap_ignored_even_with_polarity_flip():
    """Polarity differs but only `use` is shared (after stripping
    negations). 1/2 < 0.7 threshold → don't fire."""
    assert not detect_contradiction("Always use pnpm", "Never use docker")


def test_short_text_returns_false():
    assert not detect_contradiction("", "")
    assert not detect_contradiction("x", "Don't x")


def test_french_contradiction_pattern():
    a = "Toujours utiliser pnpm pour ce repo"
    b = "Ne pas utiliser pnpm pour ce repo"
    assert detect_contradiction(a, b)


# --- find_self_duplicates --------------------------------------------

def test_finds_two_lines_saying_the_same_thing():
    lines = [
        "- Always use pnpm in this repo, never npm",
        "- Use pnpm not npm in this repo",
        "- Tests live in tests/, not __tests__/",
    ]
    matches = find_self_duplicates(lines)
    assert len(matches) == 1
    assert "pnpm" in matches[0]["line_a"]
    assert "pnpm" in matches[0]["line_b"]


def test_self_duplicate_skips_short_lines():
    """Section headers and stubs would noisily match — must be skipped."""
    lines = [
        "## Project rules",
        "- pnpm",
        "- Always use pnpm in this repo, never npm",
        "- Use pnpm not npm in this repo",
    ]
    matches = find_self_duplicates(lines)
    # Short lines filtered out — only the two real rules remain to compare.
    assert len(matches) == 1


def test_no_duplicates_when_rules_are_distinct():
    lines = [
        "- Use pnpm in this repo, never npm",
        "- Always run lint:fix before committing",
        "- Tests live in tests/, not __tests__/",
        "- Deploy with kubectl apply",
    ]
    matches = find_self_duplicates(lines)
    assert matches == []


def test_self_duplicate_results_sorted_by_similarity():
    lines = [
        "- Always use pnpm in this repo, never npm",
        "- Use pnpm not npm in this repo",                         # near identical to first
        "- Always use pnpm always",                                  # subset of first
        "- Tests live in tests/",
    ]
    matches = find_self_duplicates(lines)
    # Top match should be the most similar pair
    assert matches[0]["similarity"] >= matches[-1]["similarity"]


def test_self_duplicate_handles_empty_input():
    assert find_self_duplicates([]) == []


# --- find_contradicted_lines -----------------------------------------

def test_finds_contradicted_line_in_existing_md():
    existing = [
        "## Project rules",
        "- Always use npm in this repo",
        "- Tests live in tests/",
    ]
    new_rule = "Don't use npm in this repo"
    matches = find_contradicted_lines(new_rule, existing)
    assert len(matches) == 1
    assert "npm" in matches[0]["line"]


def test_no_contradiction_when_rules_disagree_on_unrelated_topics():
    existing = [
        "- Use pnpm not npm in this repo",
        "- Deploy with kubectl apply",
    ]
    new_rule = "Always run lint:fix before committing"
    assert find_contradicted_lines(new_rule, existing) == []


def test_no_contradiction_when_rules_align():
    existing = ["- Use pnpm in this repo, never npm"]
    new_rule = "Always use pnpm not npm"
    # Same polarity (both positive on pnpm) → not a contradiction
    assert find_contradicted_lines(new_rule, existing) == []


def test_contradiction_skips_short_lines():
    existing = ["pnpm", "use", "## header"]
    new_rule = "Don't use pnpm"
    assert find_contradicted_lines(new_rule, existing) == []
