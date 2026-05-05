"""Tests for the rule.contract.must_fire_on / must_not_fire_on machinery.

These contracts are the link between the spec and the eval suite — a rule
whose contract claims a fixture but doesn't actually fire on it is the kind
of silent corruption this whole project exists to prevent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness.loader import load_rules, _matches
from pipeline import CandidateEvent
from run_evals import _rule_fires, verify_rule_contracts


def _events_for(fixture_path: Path) -> list[CandidateEvent]:
    """Lift the JSONL fixture into CandidateEvent objects (no contextual
    prev/next, which the rule predicates don't currently use)."""
    out = []
    for line in fixture_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("_marker"):
            continue
        out.append(CandidateEvent(
            session_id=obj.get("session_id", ""),
            session_short=obj.get("session_short", ""),
            agent=obj.get("agent", ""),
            timestamp=obj.get("timestamp", ""),
            role=obj.get("role", ""),
            content=obj.get("content", ""),
            tool_name=obj.get("tool_name"),
            tool_status=obj.get("tool_status"),
        ))
    return out


def test_all_shipped_contracts_hold():
    """Every must_fire_on / must_not_fire_on claim in the shipped rules.yaml
    must be true. This is the project-wide contract gate."""
    violations = verify_rule_contracts()
    assert violations == 0, f"{violations} contract violation(s) — see output"


def test_must_fire_on_simple_success_for_heuristic_rule():
    """Direct sanity check: R-HEURISTIC-ALWAYS-NEVER must fire on at least
    one event in simple_success.jsonl."""
    rs = load_rules()
    rule = next(r for r in rs.rules if r.id == "R-HEURISTIC-ALWAYS-NEVER")
    events = _events_for(REPO_ROOT / "evals" / "fixtures" / "simple_success.jsonl")
    assert any(_rule_fires(rule, ev, rs) for ev in events)


def test_must_not_fire_on_false_positive_instruction_for_constraint_rule():
    """The constraint rule must NOT fire on the long imperative user message
    — this is the issue #13 regression test, lifted to a unit test so it
    runs even if the eval harness changes."""
    rs = load_rules()
    rule = next(r for r in rs.rules if r.id == "R-CONSTRAINT-MUST-REQUIRES")
    events = _events_for(REPO_ROOT / "evals" / "fixtures"
                         / "false_positive_instruction.jsonl")
    assert not any(_rule_fires(rule, ev, rs) for ev in events)


def test_must_not_fire_on_narrative_always_for_heuristic_rule():
    """'I always thought X, but anyway' starts with 'I' — R-HEURISTIC must
    stay silent thanks to the start-anchor."""
    rs = load_rules()
    rule = next(r for r in rs.rules if r.id == "R-HEURISTIC-ALWAYS-NEVER")
    events = _events_for(REPO_ROOT / "evals" / "fixtures" / "narrative_always.jsonl")
    assert not any(_rule_fires(rule, ev, rs) for ev in events)


def test_meta_work_filter_blocks_progress_narration():
    """R-CLAIM-ASSISTANT must not fire on a message whose body matches
    the claim regex but whose head is progress narration."""
    rs = load_rules()
    rule = next(r for r in rs.rules if r.id == "R-CLAIM-ASSISTANT")
    events = _events_for(REPO_ROOT / "evals" / "fixtures" / "progress_narration.jsonl")
    assert not any(_rule_fires(rule, ev, rs) for ev in events)
