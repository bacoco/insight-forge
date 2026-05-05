"""Tests for scripts/validate_evidence.py — the JSON Schema validator and
the traceability check that makes 'rien n'est inventé' executable."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from validate_evidence import (_load_schema, _extract_source_corpus,
                                validate_schema, verify_traceability)

# Skip cleanly when jsonschema isn't installed locally — CI does install it.
pytest.importorskip("jsonschema")


# --- a minimal valid bundle, used as the baseline for negative tests ----

_VALID_BUNDLE = {
    "entry_id": "H99",
    "target_layer": "heuristic",
    "crystallized_via": "verbal-affirmation",
    "from_staging": "O99",
    "sessions": ["abcd1234"],
    "evidence": [
        {
            "kind": "trigger",
            "role": "user",
            "session_id": "abcd1234",
            "timestamp": "2026-05-01T10:00:05",
            "quote": "Always use pnpm for this repo, never npm.",
        },
        {
            "kind": "verbal-affirmation",
            "role": "user",
            "session_id": "abcd1234",
            "timestamp": "2026-05-01T10:00:20",
            "quote": "yes parfait, on part sur pnpm",
        },
    ],
    "counter_evidence": {
        "text": "Doesn't apply when an upstream tool only ships an npm script.",
        "source": "deterministic-template",
    },
    "promotion_gate": {"passed": True, "reason": "User affirmation phrase: 'yes'"},
}


# --- schema validation --------------------------------------------------

def test_minimal_valid_bundle():
    schema = _load_schema()
    errs = validate_schema(_VALID_BUNDLE, schema)
    assert errs == [], f"valid bundle failed validation: {errs}"


def test_missing_entry_id_fails():
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    del bundle["entry_id"]
    errs = validate_schema(bundle, schema)
    assert errs, "missing entry_id should fail validation"


def test_missing_evidence_fails():
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    del bundle["evidence"]
    errs = validate_schema(bundle, schema)
    assert errs


def test_empty_evidence_fails():
    """The schema requires minItems: 1 — an empty evidence list is invalid."""
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    bundle["evidence"] = []
    errs = validate_schema(bundle, schema)
    assert errs


def test_invalid_target_layer_rejected():
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    bundle["target_layer"] = "wishful_thinking"
    errs = validate_schema(bundle, schema)
    assert errs


def test_invalid_signal_rejected():
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    bundle["crystallized_via"] = "lucky-guess"
    errs = validate_schema(bundle, schema)
    assert errs


def test_entry_id_pattern_enforced():
    """entry_id must match the [A-Z]\\d+ pattern used in logic/<layer>.md."""
    schema = _load_schema()
    bundle = dict(_VALID_BUNDLE)
    bundle["entry_id"] = "lower01"
    errs = validate_schema(bundle, schema)
    assert errs


# --- traceability -------------------------------------------------------

def test_traceability_finds_quote_in_source():
    """A bundle quote must be findable as a substring of the source corpus."""
    corpus = "User said: Always use pnpm for this repo, never npm. — and the chat continued."
    errs = verify_traceability(_VALID_BUNDLE, corpus)
    # The trigger quote IS in corpus; the verbal-affirmation isn't.
    # Verify only one error fires.
    assert len(errs) == 1
    assert "yes parfait" in errs[0]


def test_traceability_passes_when_all_quotes_present():
    corpus = ("Always use pnpm for this repo, never npm. "
               "yes parfait, on part sur pnpm")
    errs = verify_traceability(_VALID_BUNDLE, corpus)
    assert errs == []


def test_traceability_fails_for_invented_quote():
    """A bundle whose quote isn't in the source must be rejected — this is
    the executable form of 'rien n'est inventé'."""
    fabricated = {
        "entry_id": "H77",
        "target_layer": "heuristic",
        "crystallized_via": "verbal-affirmation",
        "from_staging": "O77",
        "evidence": [
            {"kind": "trigger", "role": "user",
             "quote": "Use Mongoose for everything because Hibernate is too slow."},
        ],
    }
    corpus = "we discussed pgvector versus pinecone today and decided pgvector"
    errs = verify_traceability(fabricated, corpus)
    assert len(errs) == 1
    assert "Mongoose" in errs[0] or "not found" in errs[0]


def test_traceability_tolerates_truncation_ellipsis():
    """Quotes are stored truncated to ~280 chars with a trailing '…' — the
    check should still pass when the un-truncated head is in the corpus."""
    bundle = {
        "entry_id": "H88",
        "target_layer": "heuristic",
        "crystallized_via": "verbal-affirmation",
        "from_staging": "O88",
        "evidence": [
            {"kind": "trigger", "role": "user", "quote": "Always use pnpm…"},
        ],
    }
    corpus = "Always use pnpm for this repo, never npm."
    errs = verify_traceability(bundle, corpus)
    assert errs == []


def test_extract_source_corpus_skips_markers():
    """Marker lines (_marker: session_start/end) must not appear in the
    corpus — they would let synthetic content like '_marker' satisfy a
    bogus 'quote' string."""
    fixture_path = REPO_ROOT / "evals" / "fixtures" / "simple_success.jsonl"
    corpus = _extract_source_corpus(fixture_path)
    assert "_marker" not in corpus
    assert "Always use pnpm" in corpus
