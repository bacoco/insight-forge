"""Tests for harness/loader.py — load + execute the rule spec."""
from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.loader import (Rule, RuleSet, classify_with_rules, load_rules,
                              _matches, _starts_with_imperative)


def _ev(role="user", content="", tool_status=None, **kwargs):
    """Lightweight CandidateEvent stand-in — only the attrs predicates touch."""
    return SimpleNamespace(role=role, content=content, tool_status=tool_status,
                            **kwargs)


def _ruleset(rules=None, phrase_lists=None, imperative_openers=None):
    return RuleSet(
        version=1,
        rules=rules or [],
        phrase_lists=phrase_lists or {},
        imperative_openers=imperative_openers or [],
    )


def test_load_rules_default_path_works():
    """The default load_rules() call must succeed against the shipped spec."""
    rs = load_rules()
    assert rs.version >= 1
    ids = [r.id for r in rs.rules]
    assert "R-HEURISTIC-ALWAYS-NEVER" in ids
    assert "R-CONSTRAINT-MUST-REQUIRES" in ids
    assert "R-CLAIM-ASSISTANT" in ids


def test_load_rules_validates_contract_blocks():
    """Every shipped rule should have a contract — even if it's empty."""
    rs = load_rules()
    for r in rs.rules:
        assert isinstance(r.contract, dict)


def test_classify_with_rules_first_match_wins(tmp_path):
    """If two rules could match, the FIRST one in declaration order wins."""
    rules = [
        Rule(id="A", description="", when={"role": "user"}, unless=None,
              emit={"route": "staged", "type": "claim"}, contract={}),
        Rule(id="B", description="", when={"role": "user"}, unless=None,
              emit={"route": "staged", "type": "heuristic"}, contract={}),
    ]
    rs = _ruleset(rules=rules)
    ev = _ev(role="user", content="anything")
    result = classify_with_rules(ev, rs)
    assert result["rule_id"] == "A"
    assert result["type"] == "claim"


def test_classify_returns_none_when_no_rule_fires():
    rs = _ruleset(rules=[
        Rule(id="A", description="",
              when={"role": "assistant"}, unless=None,
              emit={"route": "staged", "type": "claim"}, contract={}),
    ])
    ev = _ev(role="user", content="hello")
    assert classify_with_rules(ev, rs) is None


def test_classify_unless_blocks_match():
    rs = _ruleset(rules=[
        Rule(id="A", description="",
              when={"role": "user"},
              unless={"content_length_gt": 5},
              emit={"route": "staged", "type": "claim"}, contract={}),
    ])
    short = _ev(role="user", content="ok")
    long = _ev(role="user", content="this is a long message")
    assert classify_with_rules(short, rs) is not None
    assert classify_with_rules(long, rs) is None


def test_starts_with_imperative_helper():
    openers = ["fix", "update", "crée"]
    assert _starts_with_imperative("fix the bug", openers) is True
    assert _starts_with_imperative("crée un fichier", openers) is True
    assert _starts_with_imperative("Fix the bug", openers) is True   # case-insens
    assert _starts_with_imperative("the bug is fixed", openers) is False
    assert _starts_with_imperative("", openers) is False


def test_load_rules_preserves_order(tmp_path):
    """Rule order matters for priority — the loader must not reorder."""
    p = tmp_path / "rules.yaml"
    p.write_text(textwrap.dedent("""\
        version: 1
        phrase_lists: {}
        imperative_openers: []
        rules:
          - id: FIRST
            when:
              role: user
            emit:
              route: staged
              type: heuristic
          - id: SECOND
            when:
              role: user
            emit:
              route: staged
              type: claim
        """), encoding="utf-8")
    rs = load_rules(p)
    assert [r.id for r in rs.rules] == ["FIRST", "SECOND"]
