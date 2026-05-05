"""
Insight Forge — load and execute the portable rule spec.

`load_rules(path)` returns a `RuleSet`. `RuleSet.classify(ev)` runs each rule
against an event and returns the first `RoutedEvent` produced — preserving
the priority-by-order semantics of the original `classify_and_route()`.

Why externalize?
    Tsinghua NLAH (Pan et al., 2026): harness control logic should live as a
    portable, editable artifact, not buried in controller code.
    Stanford Meta-Harness (Lee et al., 2026): once harness behavior is data,
    proposers + evals can optimize it end-to-end.

The rules.yaml format is documented in harness/README.md.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# pyyaml when available, fall back to pipeline's lite parser
try:
    import yaml as _yaml
    _HAS_PYYAML = True
except ImportError:
    _HAS_PYYAML = False

# Reuse pipeline helpers without importing the whole module at load time.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml_text(text: str) -> dict:
    if _HAS_PYYAML:
        return _yaml.safe_load(text) or {}
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from pipeline import yaml_load_simple  # noqa: E402
    return yaml_load_simple(text) or {}


# ---------------------------------------------------------------------------
# Rule data model
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    id: str
    description: str
    when: dict
    unless: Optional[dict]
    emit: dict
    contract: dict = field(default_factory=dict)


@dataclass
class RuleSet:
    version: int
    rules: list[Rule]
    phrase_lists: dict[str, list[str]]
    imperative_openers: list[str]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rules(path: Optional[Path] = None) -> RuleSet:
    """Read rules.yaml. Default location: harness/rules.yaml at repo root."""
    if path is None:
        path = _REPO_ROOT / "harness" / "rules.yaml"
    data = _load_yaml_text(Path(path).read_text(encoding="utf-8"))

    rules = [
        Rule(
            id=r["id"],
            description=r.get("description", ""),
            when=r.get("when") or {},
            unless=r.get("unless"),
            emit=r.get("emit") or {},
            contract=r.get("contract") or {},
        )
        for r in (data.get("rules") or [])
    ]
    return RuleSet(
        version=int(data.get("version", 1)),
        rules=rules,
        phrase_lists=(data.get("phrase_lists") or {}),
        imperative_openers=[s.lower() for s in (data.get("imperative_openers") or [])],
    )


# ---------------------------------------------------------------------------
# Predicate evaluator
# ---------------------------------------------------------------------------

# Pre-compiled meta-work prefix matcher (mirrors pipeline.META_WORK_PREFIXES).
# Kept here so loader.py is self-contained.
_META_WORK_PREFIXES = re.compile(
    r"^(i'?m |i am )(checking|reviewing|looking|reading|scanning|analyzing|verifying|"
    r"running|fixing|updating|writing|creating|finding|searching|examining|inspecting)\b"
    r"|^(i'?ve |i have )(reviewed|checked|looked|found|read|scanned|run|updated|written|"
    r"created|analyzed|verified|confirmed|identified|examined|inspected)\b"
    r"|^(let me |let's )(check|look|read|review|scan|run|verify|create|write|update|fix|"
    r"examine|inspect|analyze|search|find)\b"
    r"|^(checking|reading|looking|scanning|reviewing|analyzing|verifying|running|examining)\b"
    r"|^(the |this )(repo|repository|branch|file|directory|codebase|code) (is |has |contains |shows )"
    r"|^repo is (on|at|tracking)\b"
    r"|^(branch|tracking|local changes|working directory)\b",
    re.IGNORECASE,
)


def _starts_with_imperative(content: str, openers: list[str]) -> bool:
    head = content.strip().split(maxsplit=1)
    if not head:
        return False
    first = re.sub(r"[^\w]", "", head[0]).lower()
    return first in openers


def _check_atom(key: str, expected: Any, ev: Any, ruleset: RuleSet) -> bool:
    """Evaluate one predicate key/value against an event-like object."""
    content = getattr(ev, "content", "") or ""
    if key == "role":
        return getattr(ev, "role", "") == expected
    if key == "tool_status":
        return getattr(ev, "tool_status", None) == expected
    if key == "content_matches_regex":
        return bool(re.search(expected, content, re.IGNORECASE))
    if key == "content_starts_with_regex":
        return bool(re.match(expected, content, re.IGNORECASE))
    if key == "content_contains_any_phrase_list":
        phrases = ruleset.phrase_lists.get(expected, [])
        norm = content.lower()
        return any(p.lower() in norm for p in phrases)
    if key == "content_length_lt":
        return len(content) < int(expected)
    if key == "content_length_gt":
        return len(content) > int(expected)
    if key == "content_starts_with_imperative":
        is_imp = _starts_with_imperative(content, ruleset.imperative_openers)
        return is_imp == bool(expected)
    if key == "matches_meta_work_prefix":
        m = bool(_META_WORK_PREFIXES.match(content.strip()))
        return m == bool(expected)
    raise ValueError(f"Unknown predicate key: {key!r}")


def _matches(predicate: dict, ev: Any, ruleset: RuleSet) -> bool:
    """Evaluate a predicate. AND of plain keys; supports `any:` for OR."""
    if not predicate:
        return True
    for key, value in predicate.items():
        if key == "any":
            # value is a list of sub-predicates joined by OR
            if not any(_matches(sub, ev, ruleset) for sub in (value or [])):
                return False
            continue
        if key == "all":
            if not all(_matches(sub, ev, ruleset) for sub in (value or [])):
                return False
            continue
        if not _check_atom(key, value, ev, ruleset):
            return False
    return True


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_with_rules(ev: Any, ruleset: RuleSet) -> Optional[dict]:
    """Run rules in order, return the emit dict of the first that fires.

    Returns a dict with: route, type, provenance, confidence, rule_id.
    The pipeline wraps this into a full RoutedEvent.
    """
    for rule in ruleset.rules:
        if not _matches(rule.when, ev, ruleset):
            continue
        if rule.unless and _matches(rule.unless, ev, ruleset):
            continue
        emit = dict(rule.emit)
        emit["rule_id"] = rule.id
        return emit
    return None
