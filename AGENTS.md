# AGENTS.md

This file provides guidance to Codex and other coding agents working in this repository.

## Golden Rule

Take the most direct, safe, verifiable path:
- Define "done" in one sentence before starting.
- Work in small, reviewable increments — one script, rule, or contract per change.
- Use the project's existing harness: the four quality gates (`insight-forge eval`, `eval --verify-contracts`, `pytest`, `validate-evidence --evals`) are the definition of green. Run them; do not invent parallel verification.
- Prefer extending `harness/rules.yaml` and eval fixtures over ad-hoc logic in scripts.

## Repository Guidance

`CLAUDE.md` at the repo root is the detailed authority on structure, quality gates, invariants, and conventions. Read it first.

## Branch Rule

The main branch is `main`. Create feature branches for changes; do not commit directly to `main` unless explicitly asked.

## Critical Constraints

- The tool must never auto-edit a user's `CLAUDE.md`/`AGENTS.md` — proposals go to `.insight-forge/proposals/` only. Do not weaken this.
- Conservative promotion is the product: only the four closure signals crystallize an entry; `false_promotion_rate` must stay at 0% in evals.
- Every promoted entry needs concrete `counter_evidence` (Devil's Advocate) and transcript-traceable quotes (evidence bundle schema).
- No hard runtime dependencies: PyYAML stays optional with the built-in fallback parser; pipeline logic stays in `scripts/`, `insight_forge/` stays a thin CLI dispatcher.
- The skill's trigger list in `SKILL.md` frontmatter is exhaustive and user-invocable only — do not loosen it.
