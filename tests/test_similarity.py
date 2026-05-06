"""Tests for scripts/similarity.py — token similarity primitives.

These tests pin the conservative behavior we want: high Jaccard signals
near-duplicates, low Jaccard leaves things alone, the function never
treats two distinct rules as redundant just because they share function
words. False positives are worse than false negatives — a noisy detector
trains users to ignore the warning.
"""
from __future__ import annotations

import pytest

from similarity import (find_near_duplicates,
                          find_near_duplicates_in_text,
                          is_subset_of,
                          jaccard,
                          tokenize)


# --- tokenize ----------------------------------------------------------

def test_tokenize_basic():
    assert tokenize("Use pnpm not npm") == {"use", "pnpm", "npm"}


def test_tokenize_strips_french_stopwords():
    assert tokenize("Il faut toujours utiliser pnpm") == {"faut", "toujours", "utiliser", "pnpm"}


def test_tokenize_strips_english_stopwords():
    """Function words ('the', 'is', 'to', 'in') drop out so two rules
    don't look similar just because they share connectors."""
    assert tokenize("The api is in the docs") == {"api", "docs"}


def test_tokenize_drops_one_letter_tokens():
    """'a', 'i', 'l' etc. are noise."""
    assert "a" not in tokenize("a b cd ef")
    assert "i" not in tokenize("a i u")


def test_tokenize_empty():
    assert tokenize("") == set()
    assert tokenize(None) == set()


# --- jaccard -----------------------------------------------------------

def test_jaccard_identical_strings():
    assert jaccard("use pnpm", "use pnpm") == 1.0


def test_jaccard_disjoint_strings():
    assert jaccard("use pnpm", "deploy nginx") == 0.0


def test_jaccard_partial_overlap():
    """Two rules saying the same thing in different word order should score
    high. Order doesn't matter for token-level Jaccard."""
    a = "Always use pnpm not npm in this repo"
    b = "Always use pnpm in this repo, never npm"
    assert jaccard(a, b) > 0.7


def test_jaccard_unrelated_rules_score_low():
    """Rules about different topics must NOT cross-flag, even if they
    happen to use a common verb."""
    a = "Always use pnpm for package management"
    b = "Always run lint:fix before committing"
    assert jaccard(a, b) < 0.4


def test_jaccard_handles_empty():
    assert jaccard("", "") == 1.0    # both empty = trivially "same"
    assert jaccard("", "anything") == 0.0
    assert jaccard("anything", "") == 0.0


def test_jaccard_stopwords_dont_inflate_score():
    """Without stopword filtering, two rules sharing 'the is in' would look
    similar. With it, they shouldn't."""
    a = "the api is in production"
    b = "the bug is in the parser"
    assert jaccard(a, b) < 0.3


# --- is_subset_of ------------------------------------------------------

def test_subset_short_inside_long():
    assert is_subset_of("use pnpm", "always use pnpm in this repo")


def test_subset_distinct_rules_not_subset():
    assert not is_subset_of("use pnpm", "deploy nginx")


def test_subset_partial_overlap_below_threshold():
    """50% overlap with default threshold of 0.85 should be False."""
    assert not is_subset_of("use pnpm always", "use yarn always")


def test_subset_empty_short_returns_false():
    """If `short` has no meaningful tokens, claiming subset would be a
    vacuous truth — explicitly avoid it."""
    assert not is_subset_of("the the the", "any text here")


# --- find_near_duplicates ---------------------------------------------

def test_no_existing_entries_no_matches():
    assert find_near_duplicates(
        candidate_text="Always use pnpm",
        candidate_id="H01",
        candidate_session="abc12345",
        existing_entries=[],
    ) == []


def test_finds_high_overlap_match():
    """Two heuristics about the same thing in different word orders."""
    existing = [
        {"id": "H01", "text": "Use pnpm not npm",
          "session": "aaaa1111"},
    ]
    result = find_near_duplicates(
        candidate_text="Always use pnpm in this repo, never npm",
        candidate_id="H02",
        candidate_session="bbbb2222",
        existing_entries=existing,
    )
    assert len(result) == 1
    assert result[0]["id"] == "H01"
    # The match arrives via subset signal (H01's tokens are a subset of
    # the candidate's tokens), so the raw Jaccard can be lower than the
    # default 0.6 threshold — we only assert the match was found and
    # carries an actionable reason.
    assert result[0]["similarity"] > 0
    assert result[0]["reason"]


def test_skips_self_comparison():
    """An entry should never be compared to itself by ID."""
    existing = [{"id": "H01", "text": "Use pnpm", "session": "x"}]
    result = find_near_duplicates(
        candidate_text="Use pnpm",
        candidate_id="H01",
        candidate_session="x",
        existing_entries=existing,
    )
    assert result == []


def test_unrelated_entries_not_flagged():
    existing = [
        {"id": "H01", "text": "Always run lint:fix before committing",
          "session": "aaaa1111"},
        {"id": "H02", "text": "Tests live in tests/, not __tests__/",
          "session": "bbbb2222"},
    ]
    result = find_near_duplicates(
        candidate_text="Use pnpm not npm",
        candidate_id="H99",
        candidate_session="cccc3333",
        existing_entries=existing,
    )
    assert result == []


def test_results_sorted_by_similarity_desc():
    existing = [
        {"id": "H01", "text": "Use pnpm", "session": "a"},
        {"id": "H02", "text": "Use pnpm always never npm in repo", "session": "b"},
    ]
    result = find_near_duplicates(
        candidate_text="Use pnpm always never npm in this repo",
        candidate_id="H99",
        candidate_session="z",
        existing_entries=existing,
    )
    assert result[0]["id"] == "H02"  # higher overlap


def test_same_session_flagged_in_reason():
    """When two crystallized entries trace back to the same session, the
    annotation says so — same-session duplicates are stronger evidence
    of redundancy than independent crystallizations."""
    existing = [
        {"id": "H01", "text": "Use pnpm not npm in this repo",
          "session": "aaaa1111"},
    ]
    result = find_near_duplicates(
        candidate_text="Always use pnpm in this repo, never npm",
        candidate_id="H02",
        candidate_session="aaaa1111",  # same session
        existing_entries=existing,
    )
    assert "same source session" in result[0]["reason"]


def test_supersedes_existing_when_candidate_extends():
    """If the new entry is a strict expansion of the old one, the reason
    should reflect that."""
    existing = [{"id": "H01", "text": "Use pnpm", "session": "a"}]
    result = find_near_duplicates(
        candidate_text="Use pnpm always in this repo",
        candidate_id="H02",
        candidate_session="b",
        existing_entries=existing,
    )
    # H01 ⊂ H02 — the new H02 is the "expanded form" of existing H01
    assert "expanded form" in result[0]["reason"] \
        or "supersedes" in result[0]["reason"] \
        or "near-identical" in result[0]["reason"]


# --- find_near_duplicates_in_text -------------------------------------

def test_text_lines_match_candidate():
    lines = [
        "## Project rules",                # too short / heading — skipped
        "- Always use pnpm in this repo, never npm.",
        "- Tests live in tests/, not __tests__/",
    ]
    result = find_near_duplicates_in_text(
        candidate_text="Use pnpm not npm",
        text_lines=lines,
    )
    assert len(result) == 1
    assert result[0]["similarity"] >= 0.5


def test_text_lines_no_match():
    lines = ["- Deploy with kubectl apply"]
    result = find_near_duplicates_in_text(
        candidate_text="Use pnpm not npm",
        text_lines=lines,
    )
    assert result == []


def test_text_lines_skips_short_lines():
    """Short lines are usually headers / stubs and would noisily match
    almost anything via stopword removal — skip them."""
    lines = ["pnpm", "use", "- short"]  # all under 20 chars
    result = find_near_duplicates_in_text(
        candidate_text="Use pnpm not npm",
        text_lines=lines,
    )
    assert result == []


def test_text_lines_returns_only_best_match():
    """The function returns one summary, not every line — proposals get
    annotated with a single 'closest existing' line, not a wall of
    near-misses."""
    lines = [
        "- Always use pnpm not npm in this repo",
        "- Use pnpm everywhere instead of npm and yarn",
    ]
    result = find_near_duplicates_in_text(
        candidate_text="Use pnpm not npm",
        text_lines=lines,
    )
    assert len(result) == 1


# --- extra_matcher seam (opt-in semantic similarity) ------------------

def test_extra_matcher_called_when_deterministic_finds_nothing():
    """The seam: when deterministic returns no matches, an extra matcher
    can supply additional results. This is the entry point for an opt-in
    LLM/embedding provider."""
    existing = [
        {"id": "C01", "text": "Postgres is the primary store",
          "session": "aaaa1111"},
    ]

    def fake_llm_matcher(candidate, existing_entries):
        # Pretend the LLM detected a semantic contradiction.
        return [{
            "id": "C01",
            "similarity": 0.85,
            "reason": "llm: same architectural choice topic, opposite",
        }]

    result = find_near_duplicates(
        candidate_text="Always use SQLite for the data store",
        candidate_id="C99",
        candidate_session="bbbb2222",
        existing_entries=existing,
        extra_matcher=fake_llm_matcher,
    )
    assert len(result) == 1
    assert result[0]["id"] == "C01"
    assert "llm" in result[0]["reason"]


def test_extra_matcher_skipped_when_deterministic_finds_match():
    """Cost discipline: if the cheap deterministic check already found a
    match, the extra matcher is NOT called. Keeps token usage at zero
    on the common path."""
    existing = [
        {"id": "H01", "text": "Use pnpm not npm in this repo",
          "session": "aaaa1111"},
    ]
    call_count = [0]

    def fake_matcher(candidate, existing_entries):
        call_count[0] += 1
        return []

    find_near_duplicates(
        candidate_text="Always use pnpm in this repo, never npm",
        candidate_id="H02",
        candidate_session="bbbb2222",
        existing_entries=existing,
        extra_matcher=fake_matcher,
    )
    assert call_count[0] == 0, \
        "extra_matcher was invoked despite deterministic match"


def test_extra_matcher_errors_are_caught(capsys):
    """A broken matcher must NEVER crash the proposer. The error surfaces
    on stderr so the user knows, but the deterministic result wins."""
    def broken_matcher(candidate, existing):
        raise RuntimeError("my LLM provider is on fire")

    result = find_near_duplicates(
        candidate_text="Always use SQLite",
        candidate_id="C99",
        candidate_session="z",
        existing_entries=[{"id": "C01", "text": "totally unrelated rule",
                            "session": "x"}],
        extra_matcher=broken_matcher,
    )
    # No deterministic match, broken extra matcher → empty result, no crash
    assert result == []
    captured = capsys.readouterr()
    assert "extra_matcher raised" in captured.err


def test_extra_matcher_skips_self_id_in_extras():
    """If the extra matcher mistakenly returns the candidate's own id,
    it must be filtered out — same self-comparison guard as the
    deterministic path."""
    def fake(candidate, existing):
        return [{"id": "C99", "similarity": 0.8, "reason": "fake"},
                {"id": "C01", "similarity": 0.7, "reason": "real"}]

    result = find_near_duplicates(
        candidate_text="anything",
        candidate_id="C99",
        candidate_session="z",
        existing_entries=[{"id": "C01", "text": "totally unrelated"}],
        extra_matcher=fake,
    )
    assert len(result) == 1
    assert result[0]["id"] == "C01"


def test_extra_matcher_handles_malformed_returns():
    """Defensive: a matcher that returns non-dict items, or items missing
    `id`, must be filtered without crashing."""
    def malformed(candidate, existing):
        return [
            None,                                        # not a dict
            {"similarity": 0.9, "reason": "no id"},       # missing id
            {"id": "C01", "similarity": 0.7, "reason": "ok"},
        ]

    result = find_near_duplicates(
        candidate_text="x",
        candidate_id="C99",
        candidate_session="z",
        existing_entries=[{"id": "C01", "text": "totally unrelated"}],
        extra_matcher=malformed,
    )
    assert len(result) == 1
    assert result[0]["id"] == "C01"


def test_extra_matcher_returning_none_is_treated_as_empty():
    def returns_none(candidate, existing):
        return None

    result = find_near_duplicates(
        candidate_text="x",
        candidate_id="C99",
        candidate_session="z",
        existing_entries=[{"id": "C01", "text": "totally unrelated"}],
        extra_matcher=returns_none,
    )
    assert result == []
