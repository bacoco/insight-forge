"""Tests for the YAML lite parser in scripts/pipeline.py.

This parser is the fallback when PyYAML isn't installed — a critical path
for users who pip install insight-forge in a minimal environment. The bugs
hidden here would corrupt rules.yaml, evidence bundles, and the eval harness
without raising — silent corruption is the worst kind.

Each test forces the lite parser specifically (never PyYAML) so we know we're
exercising the code path the fallback users will hit.
"""
from __future__ import annotations

import pytest

from pipeline import yaml_dump_simple, yaml_load_simple, _yaml_scalar


def test_empty_dict_dump():
    assert yaml_dump_simple({}) == ""


def test_simple_key_value_dump():
    out = yaml_dump_simple({"a": 1, "b": "hello"})
    assert "a: 1" in out
    assert "b: hello" in out


def test_list_of_strings_dump():
    out = yaml_dump_simple({"items": ["a", "b", "c"]})
    assert "items:" in out
    assert "  - a" in out
    assert "  - c" in out


def test_empty_list_dump():
    out = yaml_dump_simple({"items": []})
    assert "items: []" in out


def test_nested_dict_dump():
    data = {"outer": {"inner": "v"}}
    out = yaml_dump_simple(data)
    assert "outer:" in out
    assert "  inner: v" in out


def test_round_trip_simple_dict():
    data = {"sessions": ["a3", "b9"], "count": 2, "ok": True, "missing": None}
    out = yaml_dump_simple(data) + "\n"
    parsed = yaml_load_simple(out)
    assert parsed.get("sessions") == ["a3", "b9"]
    assert parsed.get("count") == 2
    assert parsed.get("ok") is True
    assert parsed.get("missing") is None


def test_round_trip_list_of_dicts():
    data = {"observations": [
        {"id": "O01", "promoted": False, "stale": False},
        {"id": "O02", "promoted": True, "stale": False},
    ]}
    out = yaml_dump_simple(data) + "\n"
    parsed = yaml_load_simple(out)
    obs = parsed.get("observations") or []
    assert len(obs) == 2
    assert obs[0]["id"] == "O01"
    assert obs[0]["promoted"] is False
    assert obs[1]["promoted"] is True


def test_string_with_colon_is_quoted():
    """A string containing ':' must be quoted on output, otherwise the
    parser would split it into key/value on read-back."""
    data = {"text": "before: after"}
    out = yaml_dump_simple(data) + "\n"
    parsed = yaml_load_simple(out)
    assert parsed.get("text") == "before: after"


def test_string_with_accents_round_trip():
    data = {"rule": "Toujours utiliser pnpm — jamais npm."}
    out = yaml_dump_simple(data) + "\n"
    parsed = yaml_load_simple(out)
    assert parsed.get("rule") == "Toujours utiliser pnpm — jamais npm."


def test_regex_with_backslashes_round_trip():
    """Critical: rules.yaml stores regex strings. If the parser corrupts
    backslashes on round-trip, every classifier rule breaks silently."""
    data = {"pattern": r"^\s*(always|never)\b"}
    out = yaml_dump_simple(data) + "\n"
    parsed = yaml_load_simple(out)
    # The lite parser quotes strings with special chars; round-trip should
    # at minimum preserve the regex semantics. Compile both and compare.
    import re
    original = re.compile(data["pattern"], re.IGNORECASE)
    parsed_compiled = re.compile(parsed["pattern"], re.IGNORECASE)
    sample = "Always use pnpm"
    assert bool(original.match(sample)) == bool(parsed_compiled.match(sample))


def test_scalar_quoting_for_yaml_keywords():
    """'yes' / 'no' / 'true' / 'false' must be quoted on output, otherwise
    a string 'no' would parse back as the boolean False."""
    out = _yaml_scalar("no")
    assert out.startswith('"') and out.endswith('"')


def test_load_json_fallback():
    """The loader falls back to JSON parsing first — make sure that path
    works for compact JSON-shaped data (which we sometimes generate)."""
    text = '{"a": 1, "b": [1, 2, 3]}'
    parsed = yaml_load_simple(text)
    assert parsed == {"a": 1, "b": [1, 2, 3]}


def test_comments_are_ignored():
    text = """
# this is a comment
sessions:
  - id: a3
"""
    parsed = yaml_load_simple(text)
    assert parsed.get("sessions") == [{"id": "a3"}]


def test_inline_list_in_value():
    text = "tags: [a, b, c]\n"
    parsed = yaml_load_simple(text)
    assert parsed.get("tags") == ["a", "b", "c"]


def test_null_variants():
    """Explicit null tokens. The empty-string case is intentionally not tested:
    in standard YAML `key:\\n` is ambiguous between None and empty mapping,
    and the lite parser resolves it as the latter (which is fine for our use
    — we always emit explicit `null` or `[]` when we mean it)."""
    for null_form in ("~", "null"):
        text = f"value: {null_form}\n"
        parsed = yaml_load_simple(text)
        assert parsed.get("value") is None, f"failed for {null_form!r}"
