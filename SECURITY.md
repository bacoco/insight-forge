# Security

## Reporting a vulnerability

If you find a security issue, **please do not file a public GitHub issue**.

Instead:

1. Open a [GitHub Security Advisory](https://github.com/bacoco/insight-forge/security/advisories/new)
   on this repository — that creates a private channel for disclosure.
2. Or, if you cannot use GHSA, contact the maintainer through the email
   listed on the GitHub profile.

Please include:

- A description of the issue and its impact.
- A minimal reproduction (a fixture under `evals/fixtures/` is ideal —
  that way the fix has a regression test from day one).
- The affected version (commit SHA or release tag).
- Whether you've already disclosed elsewhere.

## What's in scope

- Code execution from a malicious JSONL transcript that the pipeline reads.
- Path traversal escaping `.insight-forge/` or the configured `--forge-dir`.
- Unintended network calls outside `--council` / `--challenge` modes.
- Secret leakage in proposals when `--redact` is requested.
- Evidence bundle traceability bypass (a bundle that validates with a
  quote that isn't in the source transcript).

## What's not in scope

- The behavior of `--council` / `--challenge` LLM modes once data has
  reached your configured LLM provider — that's governed by their terms.
- Bugs that require an attacker who already has write access to your
  `~/.claude/` or `~/.codex/` directories.
- Issues in upstream dependencies (`pyyaml`, `jsonschema`, `pytest`)
  unless this project's usage is itself the trigger.

## Response expectations

This is a personal project, not a vendor product. There is no SLA. In
practice:

- **Critical** (RCE, secret leak, traceability bypass): triage within
  72 hours, fix before the next release.
- **Other**: triage within two weeks.

If a fix requires breaking the eval contract for an existing fixture,
that's documented in the security advisory and a corresponding
fixture / contract update lands with the patch.

## Coordinated disclosure

If you'd like credit in the fix's release notes, mention that in the
report. Otherwise the advisory is anonymized.
