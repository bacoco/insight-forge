"""
Insight Forge — token-level similarity for near-duplicate detection.

Used by `propose_claude_md.py` to flag entries that look redundant against
each other or against an existing CLAUDE.md / AGENTS.md, **before** they
reach a copy-paste block. The point is to keep the harness from growing
unnecessarily — same conservative spirit as the rest of the project, just
applied to growth instead of promotion.

This module is **deterministic**. No LLM. The signals it surfaces are:

  - Jaccard similarity on lowercased tokens (with light stopword filtering)
  - Subset relations ("rule A's tokens are mostly contained in rule B")

Either signal is a *suggestion* the user should verify, never an
auto-action. The proposal markdown gets a `⚠ Possibly redundant: ...`
annotation; the user decides whether to merge / replace / keep both.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Conservative stopword set. Trimming these prevents two unrelated rules
# from looking similar just because they share function words ("the", "is",
# "le", "la"). Both EN and FR — the project is bilingual.
_STOPWORDS: frozenset[str] = frozenset({
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "by", "from", "as",
    "and", "or", "but", "not", "no", "yes", "if", "then", "else",
    "i", "you", "he", "she", "it", "we", "they", "them", "us",
    "this", "that", "these", "those", "there", "here", "where", "when",
    "do", "does", "did", "have", "has", "had", "will", "would", "should",
    "must", "may", "can", "could", "shall", "ought",
    # French
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "et", "ou", "mais", "ne", "pas", "que", "qui", "quoi",
    "ce", "cette", "ces", "cela", "ça", "ca",
    "il", "elle", "ils", "elles", "on", "nous", "vous",
    "est", "sont", "était", "ait", "soit",
    "à", "au", "aux", "en", "par", "pour", "sur", "sous", "avec", "sans",
    "tu", "moi", "toi", "lui", "leur", "leurs",
    "se", "s", "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
})


def tokenize(text: str) -> set[str]:
    """Lowercase, split into word tokens, drop stopwords + 1-letter tokens."""
    if not text:
        return set()
    tokens = _TOKEN_RE.findall(text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def jaccard(text_a: str, text_b: str) -> float:
    """Token-level Jaccard similarity. 0.0 = disjoint, 1.0 = identical."""
    a = tokenize(text_a)
    b = tokenize(text_b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_subset_of(short: str, long: str, threshold: float = 0.85) -> bool:
    """True when `short`'s tokens are mostly contained in `long`.

    Distinct from Jaccard because a short rule that's fully covered by a
    long rule shouldn't get penalized for the long rule's extra detail —
    the relation we want to surface is "the long version supersedes the
    short version", not "they look superficially similar."
    """
    a = tokenize(short)
    b = tokenize(long)
    if not a:
        return False
    return len(a & b) / len(a) >= threshold


SimilarityMatcher = "Callable[[str, list[dict]], list[dict]]"
"""Type alias for an extra matcher plugged into find_near_duplicates.

The matcher receives:
  - candidate_text: the new entry being checked
  - existing_entries: list of {id, text, ...} dicts

It returns a list of extra match dicts {id, similarity, reason} that the
caller will merge with deterministic results (deduplicated by id, the
first reason wins). Designed for opt-in semantic-similarity providers
(LLM, embedding service, etc.) without coupling the repo to any specific
SDK — the user supplies the callable.

Example wiring (pseudo-code):

    def my_llm_matcher(candidate, existing):
        # call your favourite LLM API, return [{id, similarity, reason}, ...]
        ...

    matches = find_near_duplicates(
        candidate_text=text,
        ...,
        extra_matcher=my_llm_matcher,
    )
"""


def find_near_duplicates(
    candidate_text: str,
    candidate_id: str,
    candidate_session: str,
    existing_entries: list[dict],
    threshold: float = 0.6,
    extra_matcher=None,
) -> list[dict]:
    """Compare candidate against every existing entry. Return matches.

    `existing_entries` is a list of dicts with at least:
      - `id`: the entry's stable identifier (H01, C03, ...)
      - `text`: the rule / claim / lesson text to compare against
      - `session` (optional): short session ID

    A match dict contains:
      - `id`: matched entry's id
      - `similarity`: Jaccard score, rounded to 2 decimals
      - `reason`: short human-readable rationale ("near-identical wording",
                  "supersedes existing", "high token overlap", ...)

    Sorted by similarity descending. Empty list when nothing matches.
    """
    matches: list[dict] = []

    for ex in existing_entries:
        ex_id = ex.get("id")
        if not ex_id or ex_id == candidate_id:
            continue  # don't compare an entry to itself
        ex_text = ex.get("text") or ""

        score = jaccard(candidate_text, ex_text)
        # Subset signals are independent: a short rule fully contained in
        # a long one (or vice versa) is redundant even when Jaccard is low,
        # because the long rule's extra tokens drag the union down.
        sub_a = is_subset_of(candidate_text, ex_text)
        sub_b = is_subset_of(ex_text, candidate_text)
        if score < threshold and not sub_a and not sub_b:
            continue

        reasons: list[str] = []
        if score >= 0.9:
            reasons.append("near-identical wording")
        elif sub_b:
            reasons.append("expanded form of existing")
        elif sub_a:
            reasons.append("supersedes existing")
        else:
            reasons.append("high token overlap")

        if (candidate_session and ex.get("session")
                and candidate_session == ex.get("session")):
            reasons.append("same source session")

        matches.append({
            "id": ex_id,
            "similarity": round(score, 2),
            "reason": "; ".join(reasons),
        })

    # Optional extra matcher (LLM-based, embedding-based, ...). Called only
    # when deterministic finds nothing — keeps token costs at zero on the
    # common path. Errors from the user-supplied matcher are caught so a
    # broken provider can never crash the proposer.
    if extra_matcher is not None and not matches:
        try:
            extras = extra_matcher(candidate_text, existing_entries) or []
            seen_ids = set()  # always empty here since `matches` is empty
            for ex in extras:
                if not isinstance(ex, dict):
                    continue
                ex_id = ex.get("id")
                if not ex_id or ex_id == candidate_id or ex_id in seen_ids:
                    continue
                seen_ids.add(ex_id)
                matches.append({
                    "id": ex_id,
                    "similarity": round(float(ex.get("similarity", 0.5)), 2),
                    "reason": ex.get("reason", "extra matcher"),
                })
        except Exception as exc:
            # Defensive: a misbehaving matcher must never break the
            # proposal. Surface a single line to stderr so users notice.
            import sys
            print(f"[insight-forge] extra_matcher raised {type(exc).__name__}: "
                  f"{exc} — falling back to deterministic only",
                  file=sys.stderr)

    matches.sort(key=lambda m: -m["similarity"])
    return matches


def find_near_duplicates_in_text(
    candidate_text: str,
    text_lines: list[str],
    threshold: float = 0.6,
    min_line_chars: int = 20,
) -> list[dict]:
    """Compare candidate against free-form text lines (e.g. CLAUDE.md).

    Returns up to one best match per call (the highest-overlap line).
    Lines shorter than `min_line_chars` after stripping are ignored —
    short lines are usually section headers or stubs, not rules.
    """
    best = None
    for raw in text_lines:
        line = raw.strip()
        # Strip common markdown bullet/heading markers before scoring.
        cleaned = re.sub(r"^(\s*[-*+]\s+|\s*#+\s+)", "", line)
        if len(cleaned) < min_line_chars:
            continue
        score = jaccard(candidate_text, cleaned)
        # Same subset-signal acceptance as find_near_duplicates: a short
        # candidate fully contained in a long line still flags.
        sub_a = is_subset_of(candidate_text, cleaned)
        sub_b = is_subset_of(cleaned, candidate_text)
        if score < threshold and not sub_a and not sub_b:
            continue
        if best is None or score > best["similarity"]:
            best = {
                "line": cleaned[:120],
                "similarity": round(score, 2),
                "reason": ("near-identical wording" if score >= 0.9
                           else "high token overlap"),
            }
    return [best] if best else []
