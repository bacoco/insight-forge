"""
Insight Forge — deterministic contradiction + self-duplicate detection.

Used by `propose_claude_md.py` to surface two kinds of cleanup signals
on the existing CLAUDE.md / AGENTS.md:

  - **Contradiction** — a newly-crystallized rule explicitly negates an
    existing line. Detected by polarity flip with high token overlap on
    non-polarity tokens.

  - **Self-duplicate** — two lines in the existing CLAUDE.md say the same
    thing. Detected by token-Jaccard or subset relation between bullet
    lines, ignoring section headers and short stubs.

Both signals are conservative and never propose actual edits. The user
sees a `⚠ Suggested removal` annotation in the proposal markdown and
decides whether to act.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Local import — keep similarity.py self-contained, reuse its primitives.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from similarity import is_subset_of, jaccard, tokenize  # noqa: E402


# Tokens that mark negation when they appear at the START of a rule.
# We classify polarity from the rule's OPENING (first ~4 tokens) rather
# than the whole text — a mixed rule like "Use pnpm, never npm" is
# positive on pnpm and negative on npm; classifying it as wholly
# negative because "never" appears would be wrong. Positive rules can
# embed negative clauses about specific targets without flipping their
# overall stance.
_LEADING_NEGATIONS: frozenset[str] = frozenset({
    # English
    "don", "dont", "doesn", "doesnt", "never", "avoid", "stop",
    "no", "without",
    # French (raw, pre-tokenization — "ne pas" lives in the leading window)
    "ne", "jamais", "sans", "aucun", "aucune",
})

# Tokens used to compute content-overlap. Drop the leading-polarity
# markers + a small set of structural words so two rules compare on
# their *subject* tokens.
_OVERLAP_DROP: frozenset[str] = frozenset({
    "not", "never", "don", "dont", "doesn", "doesnt", "no",
    "avoid", "without", "stop", "ne", "pas", "jamais", "sans",
    "use", "always", "prefer", "must", "should",
    "utilise", "utiliser", "toujours", "doit", "préférer",
})


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _leading_tokens(text: str, n: int = 4) -> list[str]:
    """First `n` lowercased word tokens of `text` (BEFORE stopword removal,
    because polarity markers like 'ne' / 'pas' are themselves stopwords
    in our normal tokenization)."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")[:n]]


def _polarity(text: str) -> str:
    """Return 'negative' if the text *opens* with a negation marker,
    otherwise 'positive'. The opening-only check correctly handles mixed
    rules like 'Use pnpm, never npm' (overall positive)."""
    head = set(_leading_tokens(text, 4))
    if head & _LEADING_NEGATIONS:
        return "negative"
    return "positive"


def detect_contradiction(text_a: str, text_b: str,
                         min_overlap: float = 0.7) -> bool:
    """True iff the two texts probably contradict each other.

    Heuristic: polarity differs AND ≥`min_overlap` of the smaller side's
    non-polarity tokens are shared.

    The high overlap requirement is what prevents false positives from
    sentence-level negation in unrelated rules — e.g. "Always use pnpm"
    and "Never use docker" both contain `use`, but only one content
    token, so the overlap is too low to fire.
    """
    pol_a = _polarity(text_a)
    pol_b = _polarity(text_b)
    if pol_a == pol_b:
        return False

    tokens_a = tokenize(text_a) - _OVERLAP_DROP
    tokens_b = tokenize(text_b) - _OVERLAP_DROP
    if not tokens_a or not tokens_b:
        return False

    smaller = min(len(tokens_a), len(tokens_b))
    overlap = len(tokens_a & tokens_b) / smaller
    return overlap >= min_overlap


def find_self_duplicates(lines: list[str],
                          jaccard_threshold: float = 0.6,
                          min_line_chars: int = 20) -> list[dict]:
    """Pairwise scan of `lines`. Return matches sorted by similarity desc.

    Each match dict contains:
      - `line_a`, `line_b`: the offending lines (truncated to 120 chars)
      - `similarity`: Jaccard score, rounded to 2 decimals
      - `reason`: short rationale ("near-identical wording", "subset
                  relation", "high token overlap")

    Lines shorter than `min_line_chars` after stripping are skipped —
    headers and stubs would noisily match.
    """
    cleaned: list[str] = []
    for raw in lines:
        s = raw.strip()
        s = re.sub(r"^(\s*[-*+]\s+|\s*#+\s+)", "", s)
        if len(s) >= min_line_chars:
            cleaned.append(s)

    matches: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i, line_a in enumerate(cleaned):
        for j, line_b in enumerate(cleaned):
            if i >= j:
                continue
            if (i, j) in seen_pairs:
                continue
            seen_pairs.add((i, j))

            score = jaccard(line_a, line_b)
            sub_a = is_subset_of(line_a, line_b)
            sub_b = is_subset_of(line_b, line_a)
            if score < jaccard_threshold and not sub_a and not sub_b:
                continue

            if score >= 0.9:
                reason = "near-identical wording"
            elif sub_a or sub_b:
                reason = "subset relation"
            else:
                reason = "high token overlap"

            matches.append({
                "line_a": line_a[:120],
                "line_b": line_b[:120],
                "similarity": round(score, 2),
                "reason": reason,
            })

    matches.sort(key=lambda m: -m["similarity"])
    return matches


def find_contradicted_lines(new_rule_text: str,
                              existing_lines: list[str],
                              min_line_chars: int = 20) -> list[dict]:
    """Compare a new rule against every line in CLAUDE.md / AGENTS.md.

    Return the lines that the new rule appears to contradict.

    Each match dict contains:
      - `line`: the contradicted text (truncated)
      - `reason`: short rationale (always "polarity flip + token overlap")
    """
    matches: list[dict] = []
    for raw in existing_lines:
        s = raw.strip()
        s = re.sub(r"^(\s*[-*+]\s+|\s*#+\s+)", "", s)
        if len(s) < min_line_chars:
            continue
        if detect_contradiction(new_rule_text, s):
            matches.append({
                "line": s[:120],
                "reason": "polarity flip + token overlap",
            })
    return matches
