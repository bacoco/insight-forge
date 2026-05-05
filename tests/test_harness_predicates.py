"""Tests for harness/loader.py:_matches() and _check_atom() — the predicate
evaluator. Every shipped rule's behavior depends on these primitives; bugs
here corrupt classification silently."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.loader import (RuleSet, _check_atom, _matches,
                              _META_WORK_PREFIXES)


def _ev(role="user", content="", tool_status=None, **kwargs):
    return SimpleNamespace(role=role, content=content, tool_status=tool_status,
                            **kwargs)


def _rs(phrase_lists=None, imperative_openers=None):
    return RuleSet(version=1, rules=[],
                    phrase_lists=phrase_lists or {},
                    imperative_openers=imperative_openers or [])


# --- atom predicates -----------------------------------------------------

def test_role_match():
    rs = _rs()
    assert _check_atom("role", "user", _ev(role="user"), rs)
    assert not _check_atom("role", "user", _ev(role="assistant"), rs)


def test_tool_status_match():
    rs = _rs()
    ev = _ev(role="tool_result", tool_status="error")
    assert _check_atom("tool_status", "error", ev, rs)
    assert not _check_atom("tool_status", "ok", ev, rs)


def test_content_matches_regex_case_insensitive():
    rs = _rs()
    ev = _ev(content="Always use pnpm")
    assert _check_atom("content_matches_regex", r"\balways\b", ev, rs)
    assert _check_atom("content_matches_regex", r"\bALWAYS\b", ev, rs)


def test_content_matches_regex_with_accents():
    """Accented characters in regexes must work — French rules depend on this."""
    rs = _rs()
    ev = _ev(content="Il faut nécessairement utiliser pnpm")
    assert _check_atom("content_matches_regex",
                        r"\b(doit|nécessite|nécessairement)\b", ev, rs)


def test_content_matches_regex_with_backslashes():
    """The regex storage path round-trips through YAML — this guards against
    backslash corruption corrupting the predicate at runtime."""
    rs = _rs()
    ev = _ev(content="this is a heading: hello")
    assert _check_atom("content_matches_regex", r"^\w+\s+is\s+a", ev, rs)


def test_content_starts_with_regex_anchored():
    rs = _rs()
    leading = _ev(content="Always use pnpm")
    body = _ev(content="I always think this")
    pat = r"^\s*(always|never)\b"
    assert _check_atom("content_starts_with_regex", pat, leading, rs)
    assert not _check_atom("content_starts_with_regex", pat, body, rs)


def test_content_contains_any_phrase_list():
    rs = _rs(phrase_lists={"affirmation": ["yes", "parfait", "exact"]})
    ev_match = _ev(content="oui parfait, on part sur ça")
    ev_no = _ev(content="non, pas du tout")
    assert _check_atom("content_contains_any_phrase_list", "affirmation", ev_match, rs)
    assert not _check_atom("content_contains_any_phrase_list", "affirmation", ev_no, rs)


def test_content_length_thresholds():
    rs = _rs()
    short = _ev(content="hi")
    long = _ev(content="x" * 500)
    assert _check_atom("content_length_lt", 100, short, rs)
    assert not _check_atom("content_length_lt", 100, long, rs)
    assert _check_atom("content_length_gt", 100, long, rs)
    assert not _check_atom("content_length_gt", 100, short, rs)


def test_content_starts_with_imperative_true():
    rs = _rs(imperative_openers=["fix", "crée", "update"])
    ev_imp = _ev(content="Fix the broken auth flow")
    ev_not = _ev(content="The bug is fixed in the new branch")
    assert _check_atom("content_starts_with_imperative", True, ev_imp, rs)
    assert _check_atom("content_starts_with_imperative", False, ev_not, rs)


def test_content_starts_with_imperative_false_match():
    """Asking 'is NOT imperative' should pass when the message isn't."""
    rs = _rs(imperative_openers=["fix"])
    ev = _ev(content="Always use pnpm")
    assert _check_atom("content_starts_with_imperative", False, ev, rs)


def test_meta_work_prefix_pattern():
    """The meta-work filter must catch English progress narration."""
    assert _META_WORK_PREFIXES.match("I'm checking the auth tests")
    assert _META_WORK_PREFIXES.match("Let me check the config")
    assert _META_WORK_PREFIXES.match("I've reviewed the diff")
    assert not _META_WORK_PREFIXES.match("Ruff is faster than flake8")


def test_unknown_predicate_raises():
    rs = _rs()
    with pytest.raises(ValueError):
        _check_atom("unknown_key", "x", _ev(), rs)


# --- composition: AND / any: / all: -------------------------------------

def test_and_composition():
    rs = _rs()
    pred = {"role": "user", "content_length_gt": 5}
    ev_pass = _ev(role="user", content="this is long enough")
    ev_fail_role = _ev(role="assistant", content="this is long enough")
    ev_fail_len = _ev(role="user", content="hi")
    assert _matches(pred, ev_pass, rs)
    assert not _matches(pred, ev_fail_role, rs)
    assert not _matches(pred, ev_fail_len, rs)


def test_any_composition_or_logic():
    rs = _rs()
    pred = {"any": [{"content_length_gt": 100},
                     {"content_starts_with_regex": r"^urgent"}]}
    ev_a = _ev(content="x" * 200)
    ev_b = _ev(content="urgent: ship now")
    ev_c = _ev(content="just a short normal message")
    assert _matches(pred, ev_a, rs)
    assert _matches(pred, ev_b, rs)
    assert not _matches(pred, ev_c, rs)


def test_empty_predicate_always_matches():
    rs = _rs()
    assert _matches({}, _ev(), rs)


def test_all_composition_explicit():
    rs = _rs()
    pred = {"all": [{"role": "user"}, {"content_length_gt": 5}]}
    assert _matches(pred, _ev(role="user", content="long message"), rs)
    assert not _matches(pred, _ev(role="user", content="hi"), rs)


# --- previous_event composite predicate --------------------------------

def test_previous_event_matches_role():
    rs = _rs()
    ev = _ev(role="user", content="anything",
              prev_role="tool_result", prev_content="error: file not found")
    pred = {"previous_event": {"role": "tool_result"}}
    assert _matches(pred, ev, rs)


def test_previous_event_does_not_match_when_role_differs():
    rs = _rs()
    ev = _ev(role="user", content="anything",
              prev_role="assistant", prev_content="some message")
    pred = {"previous_event": {"role": "tool_result"}}
    assert not _matches(pred, ev, rs)


def test_previous_event_with_regex():
    rs = _rs()
    ev = _ev(role="user", content="now what?",
              prev_role="tool_result",
              prev_content="ModuleNotFoundError: No module named 'jwt'")
    pred = {"previous_event": {
        "role": "tool_result",
        "content_matches_regex": r"ModuleNotFoundError",
    }}
    assert _matches(pred, ev, rs)


def test_previous_event_handles_missing_prev_fields():
    """First event in a session has no previous — predicate should return
    False for any condition rather than crash."""
    rs = _rs()
    ev = _ev(role="user", content="first turn")  # no prev_role / prev_content
    pred = {"previous_event": {"role": "assistant"}}
    assert not _matches(pred, ev, rs)


def test_previous_event_combined_with_other_predicates():
    """previous_event composes with the rest of the predicate (AND)."""
    rs = _rs()
    ev_match = _ev(role="user", content="ok let's continue",
                    prev_role="tool_result")
    ev_fail_role = _ev(role="assistant", content="ok let's continue",
                        prev_role="tool_result")
    ev_fail_prev = _ev(role="user", content="ok let's continue",
                        prev_role="user")
    pred = {"role": "user", "previous_event": {"role": "tool_result"}}
    assert _matches(pred, ev_match, rs)
    assert not _matches(pred, ev_fail_role, rs)
    assert not _matches(pred, ev_fail_prev, rs)


# --- resolve_extra() — emit.extra resolution ---------------------------

def test_resolve_extra_passes_literals_through():
    from harness.loader import resolve_extra
    emit = {"extra": {"answer": 42, "tag": "literal", "ok": True}}
    out = resolve_extra(emit, _ev())
    assert out == {"answer": 42, "tag": "literal", "ok": True}


def test_resolve_extra_reads_event_attribute():
    from harness.loader import resolve_extra
    emit = {"extra": {"failure_mode": {"from": "content"}}}
    out = resolve_extra(emit, _ev(content="ImportError: jwt"))
    assert out == {"failure_mode": "ImportError: jwt"}


def test_resolve_extra_truncates_with_max_chars():
    from harness.loader import resolve_extra
    long = "x" * 500
    emit = {"extra": {"failure_mode": {"from": "content", "max_chars": 100}}}
    out = resolve_extra(emit, _ev(content=long))
    assert len(out["failure_mode"]) == 100


def test_resolve_extra_handles_missing_attribute():
    """`{from: tool_name}` against an event without tool_name should produce
    an empty string, not crash."""
    from harness.loader import resolve_extra
    emit = {"extra": {"tool": {"from": "tool_name"}}}
    out = resolve_extra(emit, _ev())
    assert out == {"tool": ""}


def test_resolve_extra_empty_when_no_extra_block():
    from harness.loader import resolve_extra
    assert resolve_extra({}, _ev()) == {}
    assert resolve_extra({"extra": None}, _ev()) == {}
