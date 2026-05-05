# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-05

First tagged version. The project is shippable as a personal tool with full executable
trust contracts; the open-source-readability axis is in active iteration.

### Added

- **`/insight-forge` skill** — single-command invocation from Claude Code or Codex CLI.
  Reads JSONL session transcripts, extracts typed events, crystallizes against four
  closure signals (verbal-affirmation, empirical-resolution, topic-abandonment,
  artifact-commitment), and writes a reviewable proposal to
  `.insight-forge/proposals/<UTC-timestamp>.md` — never auto-edits `CLAUDE.md` /
  `AGENTS.md`.
- **`scripts/run.py`** — orchestrator that ties the extractors, pipeline, and proposal
  writer behind one entry point, with incremental cursor (`.insight-forge/.last_run`).
- **Three-stage ARA pipeline** — Context Harvester, Event Router, Maturity Tracker, all
  in `scripts/pipeline.py`.
- **Portable rule spec** at `harness/rules.yaml` for the regex-shaped classifier paths
  (`R-HEURISTIC-ALWAYS-NEVER`, `R-CONSTRAINT-MUST-REQUIRES`, `R-CLAIM-ASSISTANT`),
  loaded by `harness/loader.py`. Each rule names the eval fixtures it must (or must
  not) fire on via the `contract:` block.
- **Eval harness** at `evals/` — 15 fixtures + 1 known gap, regression-tested via
  `python3 scripts/run_evals.py`. Headline metrics: `false_promotion_rate`,
  `provenance_coverage`. Contract verifier: `--verify-contracts`.
- **Eval-graded mutation proposer** at `scripts/propose_rules.py` — sandboxed
  candidate edits to `rules.yaml`, scored by eval delta, written to
  `harness/proposals/<ts>.yaml` for review (never auto-applied).
- **Evidence bundle layer** at `.insight-forge/evidence/bundles/<entry_id>.yaml` —
  machine-readable provenance per crystallized entry, with trigger and closure
  quotes.
- **JSON Schema for evidence bundles** at `schemas/evidence_bundle.schema.json` and
  validator at `scripts/validate_evidence.py`. The `--source` flag enforces that
  every quote in a bundle is a substring of the named source transcript — making
  *"every suggestion cites your transcripts"* executable.
- **GitHub Actions CI** — runs all four quality gates (regression evals, contract
  verifier, unit tests, evidence traceability) on Python 3.10, 3.11, 3.12.
- **`insight-forge` CLI** — minimal argparse dispatcher with subcommands
  (`scan`, `eval`, `propose`, `validate-evidence`, `doctor`). Installed via
  `pip install -e ".[dev]"` and an entry point in `pyproject.toml`. Existing
  `python3 scripts/<name>.py` invocations stay supported (the `SKILL.md` flow
  uses them).
- **Secret detector** (`scripts/redact.py`) and `--redact` flag on the proposal
  writer. Default behavior warns; `--redact` replaces matches with
  `<REDACTED:type>`. Patterns cover AWS / GitHub / OpenAI / Anthropic credentials,
  JWTs, auth headers, URLs with embedded credentials, password key=value pairs,
  emails, and home directory paths.
- **`PRIVACY.md`** — local-first posture; what goes over the network (nothing, by
  default); evidence bundles can contain verbatim transcript fragments by design.
- **`SECURITY.md`** — GHSA disclosure channel, scope, response expectations.
- **`CONTRIBUTING.md`** — setup, the four quality gates, common contribution
  patterns (adding fixtures, rules, schema fields), things we don't accept.
- **Documentation set**: `README.md` (marketing), `TECHNICAL.md` (architecture
  reference), `docs/how-it-works.md` (algorithm walkthrough with paper-to-code
  mapping), `harness/README.md` (rule spec), `evals/README.md` (fixture format),
  `harness/proposals/README.md` (proposer output format), `docs/ara-methodology-study.md`.

### Tests

- 94 unit tests under `tests/` covering the YAML lite parser, harness loader,
  predicate evaluator, contract verifier, evidence schema + traceability,
  CLI dispatch, and the redactor.
- 15 regression fixtures + 1 known gap covering both languages (FR / EN), all
  four closure signals, raw user instructions vs project rules, recovered vs
  abandoned tool errors, and a mixed-language transcript.

### Notes

The classifier paths still hardcoded in `pipeline.py` (dead_end, pivot,
decision, experiment, question) are scheduled for migration into
`harness/rules.yaml` once the schema gains an `extra:` clause and context
predicates. This is tracked as the next feature work.
