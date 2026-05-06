# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Near-duplicate detection in proposals.** New `scripts/similarity.py`
  with token-level Jaccard + subset-relation checks. The proposer now
  annotates each entry with a `⚠ Possibly redundant: <id>` line when a
  near-duplicate exists in the same layer or in the project's existing
  `CLAUDE.md` / `AGENTS.md`. Friendly stderr summary surfaces the count.
  Conservative by design: stopwords (EN + FR) are filtered, one-letter
  tokens dropped, and the proposer never removes or hides any entry —
  the annotation is a suggestion the user reviews.
- New eval fixture `near_duplicate_heuristic` (two sessions producing
  near-duplicate heuristics) + 26 unit tests in `test_similarity.py` +
  3 integration tests in `test_propose_claude_md.py`.
- **Suggested-removal annotations.** New `scripts/contradiction.py`
  detects (a) lines in the existing `CLAUDE.md` / `AGENTS.md` that a
  newly-crystallized rule appears to contradict (polarity-flip with
  high token overlap), and (b) self-duplicates within the existing
  file (token-Jaccard or subset relation between bullet lines). The
  proposer adds `⚠ Suggested removal` annotations under each entry
  and a `Cleanup — self-duplicates in your existing file` section
  when applicable. Friendly stderr summary lists each warning type
  separately. Polarity is detected from the rule's leading tokens so
  mixed rules ("Use pnpm, never npm") aren't misclassified.
- 28 unit tests in `test_contradiction.py` covering polarity
  classification (EN + FR), contradiction detection over realistic
  positive/negative pairs, self-duplicate scanning with header
  filtering, and contradiction integration against existing CLAUDE.md.
- **artifact-commitment closure signal (MVP)**. Implements signal 4
  of the ARA closure-signal set, which had been a TODO since the
  project's first commit. Detection is deterministic and uses two
  passes: (1) path mentioned in the rule + path exists on disk under
  the project root; (2) tool name mentioned in the rule + canonical
  marker file exists OR config file references the tool (e.g.
  `[tool.ruff]` in `pyproject.toml`, `"packageManager": "pnpm@..."`
  in `package.json`). No git walk, no AST. Conservative — fires only
  on hard on-disk evidence.
- Inserted in `evaluate_maturity` before topic-abandonment (artifact-
  commitment is stronger evidence than silence over time). When
  `project_root` is absent (e.g. pipeline run with an unrelated
  forge_dir), the signal silently skips — preserves backward
  compatibility.
- 26 unit tests in `test_artifact_commitment.py` (path extraction,
  tool extraction, all three matcher branches, defensive paths) +
  3 integration tests in `test_pipeline_artifact_commitment.py`
  (signal does not fire without marker, fires when lockfile exists,
  silent when project_root missing).
- **Opt-in semantic similarity seam.** `find_near_duplicates` now
  accepts an `extra_matcher` callable that's invoked only when the
  deterministic check finds nothing — keeps token cost at zero on
  the common path. The callable receives `(candidate, existing)` and
  returns extra `{id, similarity, reason}` matches. Designed for
  LLM / embedding providers without coupling the repo to any specific
  SDK. Defensive: errors from a misbehaving provider surface on
  stderr and never crash the proposer; malformed return values are
  filtered. 6 unit tests pin the contract.

### Fixed

- `propose_claude_md.py:filter_recent` no longer raises
  `UnboundLocalError` when PyYAML's alphabetically-sorted output places
  `date:` before `id:` in `trace/session_index.yaml` (issue #30).

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
