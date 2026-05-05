"""
Insight Forge — secret detection + redaction for proposals.

The promise: no obvious secret should land in a copy-paste block without
a warning. This module is the executable form of that promise.

Two pieces:

- `find_secrets(text)` returns a list of {type, span, sample} matches.
- `redact(text)` replaces each match with `<REDACTED:<type>>` so the
  proposal stays human-readable but the secret is gone.

Patterns are conservative — false positives are worse than false negatives
here, because a noisy detector trains users to ignore the warning. We
aim for the obvious cases: well-known prefix tokens (AWS, GitHub, OpenAI,
Anthropic, JWT), URLs with embedded auth, and key/value pairs whose key
strongly suggests credentials.

Patterns NOT included:
- Generic high-entropy strings — too many false positives.
- Bare integers / UUIDs — they're rarely sensitive on their own.
- Phone numbers — locale-dependent, low value-to-noise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (label, regex). Order matters only for cosmetics — find_secrets walks
# every pattern. Use named groups sparingly; we read the whole match.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    # AWS access key ID — well-known fixed prefix
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # GitHub personal / installation / OAuth tokens (gh<role>_)
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    # OpenAI API keys (sk-, post-2024 sometimes sk-proj-)
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b")),
    # Anthropic API keys (sk-ant-...)
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}\b")),
    # JWT — three base64url segments separated by dots, starts with eyJ
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    # HTTP Authorization header content with Bearer or Basic
    ("auth_header", re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_\-\.\+/=]{20,}\b")),
    # URLs with auth: scheme://user:password@host
    ("url_with_auth", re.compile(r"https?://[^\s/:@]+:[^\s@]+@[^\s]+")),
    # password / secret / api_key key=value or key: value
    ("password_kv", re.compile(
        r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)"
        r"\s*[:=]\s*['\"]?([^\s'\"]{6,})", re.IGNORECASE)),
    # Email addresses — common low-risk PII; users can ignore the warning if
    # they intend to share, but they should see it.
    ("email", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")),
    # Home directory paths revealing the user's username
    ("home_path", re.compile(r"(?:/Users|/home)/[a-zA-Z][a-zA-Z0-9_\-\.]*")),
]


@dataclass(frozen=True)
class SecretMatch:
    type: str
    start: int
    end: int
    sample: str


def find_secrets(text: str) -> list[SecretMatch]:
    """Return every potential-secret match in `text`, sorted by position.

    The list may contain overlapping matches when two patterns both fire
    on the same span (e.g. an email inside a password_kv value). The
    redactor handles overlap by walking right-to-left.
    """
    if not text:
        return []
    matches: list[SecretMatch] = []
    for label, pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            matches.append(SecretMatch(type=label, start=m.start(), end=m.end(),
                                         sample=m.group(0)))
    matches.sort(key=lambda m: (m.start, -m.end))
    return matches


def has_secrets(text: str) -> bool:
    """Cheap predicate — short-circuits on the first match."""
    if not text:
        return False
    for _, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def redact(text: str, mode: str = "tag") -> str:
    """Replace every potential secret with a placeholder.

    mode='tag' (default): "<REDACTED:type>"
    mode='blank':         "<REDACTED>"
    """
    if not text:
        return text
    matches = find_secrets(text)
    if not matches:
        return text
    # Walk right-to-left so spans stay valid as we splice.
    result = text
    seen_ranges: list[tuple[int, int]] = []
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        # Skip overlap with an already-redacted later span
        if any(m.end <= s or m.start >= e for s, e in seen_ranges):
            # Disjoint with all seen — keep going.
            pass
        if any(not (m.end <= s or m.start >= e) for s, e in seen_ranges):
            continue  # overlaps a span we already redacted
        placeholder = f"<REDACTED:{m.type}>" if mode == "tag" else "<REDACTED>"
        result = result[:m.start] + placeholder + result[m.end:]
        seen_ranges.append((m.start, m.end))
    return result


def secrets_summary(text: str) -> str:
    """Compact human-readable list of secret types found in `text`.

    Used in the proposal warning header so the user sees what kind of
    sensitive material was detected without seeing the values themselves.
    """
    matches = find_secrets(text)
    if not matches:
        return ""
    by_type: dict[str, int] = {}
    for m in matches:
        by_type[m.type] = by_type.get(m.type, 0) + 1
    return ", ".join(f"{t} (×{c})" for t, c in sorted(by_type.items()))
