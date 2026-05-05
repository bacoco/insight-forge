"""Tests for the mutation operators in scripts/propose_rules.py.

Each operator is a pure function: rule + argument → new rule. We test
them in isolation here so the proposer's scoring/sandbox loop has solid
foundations.
"""
from __future__ import annotations

import pytest

from propose_rules import (mutation_add_context_predicate,
                            mutation_add_unless_predicate,
                            mutation_regex_alternation_extend,
                            extract_prev_roles)


# --- regex_alternation_extend -----------------------------------------

def test_extend_appends_to_alternation():
    rule = {
        "id": "R-X",
        "when": {"content_starts_with_regex": r"^\s*(foo|bar)\b"},
        "emit": {"route": "staged"},
    }
    out = mutation_regex_alternation_extend(rule, "baz")
    assert out is not None
    pattern = out["when"]["content_starts_with_regex"]
    assert "foo" in pattern and "bar" in pattern and "baz" in pattern


def test_extend_returns_none_when_candidate_already_present():
    rule = {
        "id": "R-X",
        "when": {"content_starts_with_regex": r"^(foo|bar)\b"},
        "emit": {},
    }
    assert mutation_regex_alternation_extend(rule, "foo") is None
    assert mutation_regex_alternation_extend(rule, "FOO") is None  # case-insens


def test_extend_returns_none_when_no_alternation_group():
    rule = {
        "id": "R-X",
        "when": {"content_starts_with_regex": r"^plain pattern"},
        "emit": {},
    }
    assert mutation_regex_alternation_extend(rule, "foo") is None


def test_extend_does_not_mutate_input():
    rule = {
        "id": "R-X",
        "when": {"content_starts_with_regex": r"^(foo|bar)\b"},
        "emit": {},
    }
    original_pattern = rule["when"]["content_starts_with_regex"]
    mutation_regex_alternation_extend(rule, "baz")
    assert rule["when"]["content_starts_with_regex"] == original_pattern


# --- add_unless_predicate ---------------------------------------------

def test_unless_creates_block_when_missing():
    rule = {"id": "R-X", "when": {"role": "user"}, "emit": {}}
    out = mutation_add_unless_predicate(rule, {"content_length_gt": 200})
    assert out["unless"] == {"any": [{"content_length_gt": 200}]}


def test_unless_appends_to_existing_any_block():
    rule = {
        "id": "R-X",
        "when": {"role": "user"},
        "unless": {"any": [{"content_length_gt": 100}]},
        "emit": {},
    }
    out = mutation_add_unless_predicate(rule, {"content_starts_with_imperative": True})
    branches = out["unless"]["any"]
    assert {"content_length_gt": 100} in branches
    assert {"content_starts_with_imperative": True} in branches
    assert len(branches) == 2


def test_unless_normalizes_flat_block_to_any_list():
    """A flat `unless: {key: val}` block gets converted to `any:`-list when a
    new branch is added — so the OR semantics are explicit and visible."""
    rule = {
        "id": "R-X",
        "when": {},
        "unless": {"content_length_gt": 100},
        "emit": {},
    }
    out = mutation_add_unless_predicate(rule, {"matches_meta_work_prefix": True})
    assert out["unless"] == {"any": [
        {"content_length_gt": 100},
        {"matches_meta_work_prefix": True},
    ]}


def test_unless_returns_none_when_predicate_already_present():
    rule = {
        "id": "R-X",
        "when": {},
        "unless": {"any": [{"content_length_gt": 200}]},
        "emit": {},
    }
    assert mutation_add_unless_predicate(rule, {"content_length_gt": 200}) is None


def test_unless_does_not_mutate_input():
    rule = {"id": "R-X", "when": {}, "unless": {"any": [{"x": 1}]}, "emit": {}}
    mutation_add_unless_predicate(rule, {"y": 2})
    assert rule["unless"] == {"any": [{"x": 1}]}


# --- add_context_predicate --------------------------------------------

def test_context_adds_previous_event_role():
    rule = {"id": "R-X", "when": {"role": "user"}, "emit": {}}
    out = mutation_add_context_predicate(rule, "tool_result")
    assert out["when"] == {
        "role": "user",
        "previous_event": {"role": "tool_result"},
    }


def test_context_returns_none_when_previous_event_already_set():
    rule = {
        "id": "R-X",
        "when": {"role": "user", "previous_event": {"role": "assistant"}},
        "emit": {},
    }
    assert mutation_add_context_predicate(rule, "user") is None


def test_context_does_not_mutate_input():
    rule = {"id": "R-X", "when": {"role": "user"}, "emit": {}}
    mutation_add_context_predicate(rule, "tool_result")
    assert "previous_event" not in rule["when"]


# --- extract_prev_roles -----------------------------------------------

def test_extract_prev_roles_walks_session():
    fixture = """\
{"_marker": "session_start"}
{"role": "user", "content": "hello"}
{"role": "assistant", "content": "hi"}
{"role": "tool_use", "content": "ls", "tool_name": "Bash"}
{"role": "tool_result", "content": "[file]", "tool_status": "ok"}
{"role": "user", "content": "thanks"}
{"_marker": "session_end"}
"""
    roles = extract_prev_roles(fixture)
    assert "user" in roles
    assert "assistant" in roles
    assert "tool_use" in roles
    assert "tool_result" in roles


def test_extract_prev_roles_resets_at_session_boundary():
    """Each session_start clears the prev-role tracker so the first event
    of session 2 doesn't get prev_role=last_event_of_session_1."""
    fixture = """\
{"_marker": "session_start"}
{"role": "user", "content": "a"}
{"_marker": "session_end"}
{"_marker": "session_start"}
{"role": "user", "content": "b"}
{"_marker": "session_end"}
"""
    # The only inter-event prev is none — the second user has no prev within
    # its session, and the first user has no prev period.
    roles = extract_prev_roles(fixture)
    assert roles == []


def test_extract_prev_roles_dedupes():
    fixture = """\
{"_marker": "session_start"}
{"role": "user", "content": "a"}
{"role": "user", "content": "b"}
{"role": "user", "content": "c"}
{"_marker": "session_end"}
"""
    roles = extract_prev_roles(fixture)
    assert roles == ["user"]
