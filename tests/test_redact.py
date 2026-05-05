"""Tests for scripts/redact.py — secret detection and redaction.

Discipline: false positives are worse than false negatives. A noisy
detector trains users to ignore the warning. These tests pin the
patterns to the obvious cases (well-known prefix tokens, URLs with auth,
keyed credentials) and explicitly assert non-detection on innocuous text.
"""
from __future__ import annotations

import pytest

from redact import find_secrets, has_secrets, redact, secrets_summary


# --- positive cases (must detect) --------------------------------------

@pytest.mark.parametrize("kind,sample", [
    ("aws_access_key", "AKIAIOSFODNN7EXAMPLE"),
    ("github_token", "ghp_AAAA1111BBBB2222CCCC3333DDDD4444EEEE"),
    ("openai_key", "sk-proj-AAAABBBBCCCCDDDDEEEEFFFF11112222"),
    ("anthropic_key", "sk-ant-api03_AAAA1111BBBB2222CCCC3333DDDD4444"),
    ("jwt", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
    ("auth_header", "Bearer abcdef0123456789ABCDEF0123456789"),
    ("url_with_auth", "https://admin:s3cret@internal.example.com/api"),
    ("password_kv", "password=hunter2hunter"),
    ("password_kv", "secret: my-very-real-secret-token"),
    ("email", "loic.example@gmail.com"),
    ("home_path", "/Users/loic/develop/secret-project"),
    ("home_path", "/home/alice/.ssh/id_rsa"),
])
def test_detects_known_secret(kind, sample):
    matches = find_secrets(f"some context {sample} more context")
    assert any(m.type == kind for m in matches), \
        f"{kind} pattern did not match {sample!r}; got {[m.type for m in matches]}"
    assert has_secrets(sample) is True


def test_multiple_secrets_in_one_text():
    text = "AKIAIOSFODNN7EXAMPLE and email user@example.com"
    matches = find_secrets(text)
    types = {m.type for m in matches}
    assert "aws_access_key" in types
    assert "email" in types


# --- negative cases (must NOT detect) ----------------------------------

@pytest.mark.parametrize("text", [
    "Just plain English text with no secrets at all.",
    "let's go with pnpm for this repo",
    "the test file is in tests/auth/login.test.ts",
    "Always use ruff for lint",
    "1234 5678 9012 3456",      # 16 digits but not an AKIA prefix
    "[H01]: heuristic crystallized at 2026-05-01",
    "/usr/local/bin/python3",   # absolute path but not a home dir
    "/var/log/sys.log",
])
def test_innocuous_text_clean(text):
    matches = find_secrets(text)
    assert matches == [], f"false positive on {text!r}: {[m.type for m in matches]}"
    assert has_secrets(text) is False


def test_empty_text():
    assert find_secrets("") == []
    assert find_secrets(None) == []
    assert has_secrets("") is False


# --- redaction ---------------------------------------------------------

def test_redact_replaces_secret_with_tag():
    text = "Use AKIAIOSFODNN7EXAMPLE for now"
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "<REDACTED:aws_access_key>" in out


def test_redact_handles_multiple_matches():
    text = "key=AKIAIOSFODNN7EXAMPLE; mail=alice@example.com"
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "alice@example.com" not in out


def test_redact_preserves_non_secret_text():
    text = "Always use pnpm not npm"
    assert redact(text) == text


def test_redact_blank_mode():
    text = "user/Users/alice/.bashrc"
    out = redact(text, mode="blank")
    assert "<REDACTED>" in out
    assert "/Users/alice" not in out


def test_secrets_summary_compact():
    text = "AKIAIOSFODNN7EXAMPLE then alice@example.com and bob@example.org"
    summary = secrets_summary(text)
    assert "aws_access_key" in summary
    assert "email" in summary
    assert "(×2)" in summary  # two emails


def test_secrets_summary_empty_when_clean():
    assert secrets_summary("just plain text") == ""


# --- ordering ----------------------------------------------------------

def test_find_secrets_returns_sorted_by_position():
    text = "first AKIAIOSFODNN7EXAMPLE then alice@example.com"
    matches = find_secrets(text)
    positions = [m.start for m in matches]
    assert positions == sorted(positions)
