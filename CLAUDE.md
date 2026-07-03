# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Insight Forge, v0.1.0 — an ARA-style cross-session learner for Claude Code and Codex CLI. It reads JSONL session transcripts (`~/.claude/projects/` or `~/.codex/sessions/`), extracts typed events through a 3-stage pipeline (Context Harvester → Event Router → Maturity Tracker), maintains a knowledge base under the target project's `.insight-forge/` (claims, heuristics, dead_ends, evidence), and proposes — never auto-applies — diffs for `CLAUDE.md`/`AGENTS.md`. GitHub: `bacoco/insight-forge`. License MIT. Main branch: `main`.

It ships in two forms: a Claude Code/Codex skill (root `SKILL.md`, which clones the repo and runs `scripts/` directly) and a pip-installable CLI (`insight-forge`, a thin dispatcher in `insight_forge/cli.py` that maps subcommands to the same scripts).

## Structure

```
SKILL.md                 # The skill: triggers, pipeline flow (user-invocable ONLY)
scripts/                 # The actual pipeline (house style: script-oriented)
│  pipeline.py, run.py, extract_claude.py, extract_codex.py,
│  propose_rules.py, propose_claude_md.py, contradiction.py, council.py,
│  artifact_commitment.py, similarity.py, routing.py, redact.py,
│  render_evidence.py, validate_evidence.py, run_evals.py
insight_forge/           # Thin CLI dispatcher package (only this ships in the wheel)
harness/                 # Declarative crystallization rules (rules.yaml + loader.py)
references/              # Protocol docs: event taxonomy, devils-advocate, council,
│                        # contradiction, crystallization rules, transcript formats
schemas/                 # evidence_bundle.schema.json
evals/                   # Regression fixtures + expected outputs (synthetic transcripts)
tests/                   # pytest unit tests
docs/                    # how-it-works.md, ara-methodology-study.md
templates/               # HTML evidence rendering
TECHNICAL.md             # Pipeline internals
```

## Quality gates (run all four before claiming done)

```bash
pip install -e ".[dev]"                    # pyyaml, pytest, jsonschema

insight-forge eval                         # 1. Regression evals — false_promotion_rate must stay 0%
insight-forge eval --verify-contracts      # 2. Harness contracts — must_fire_on / must_not_fire_on
pytest                                     # 3. Unit tests
insight-forge validate-evidence --evals    # 4. Evidence bundles — every quote traceable to source
```

Running scripts directly stays supported (e.g. `python3 scripts/run_evals.py --verify-contracts`) — this is what SKILL.md uses since the skill does not pip-install. `insight-forge doctor` diagnoses the local environment. CI (`.github/workflows/evals.yml`) gates all four on every push/PR.

## Core invariants (do not weaken)

- **Never auto-edit** the user's `CLAUDE.md`/`AGENTS.md` — proposals land in `.insight-forge/proposals/` only.
- **Default: do not promote.** Only four closure signals earn crystallization: topic abandonment, verbal affirmation, empirical resolution, artifact commitment. No scoring, no LLM-judged maturity.
- **Devil's Advocate is mandatory** — every crystallization must carry concrete `counter_evidence`; vague counters are rejected.
- **Every suggestion cites transcripts** — evidence bundles with untraceable quotes fail the build (gate 4 makes this executable).
- **The skill is user-invocable only** — the trigger list in SKILL.md frontmatter is exhaustive; do not loosen it.
- **Incremental** — sessions already processed (before `.insight-forge/.last_run`) are never re-read.

## Conventions

- No hard runtime dependencies: PyYAML is optional, with a built-in lite YAML fallback parser (covered by `tests/test_yaml_loader.py`). Keep new code dependency-free or optional-with-fallback.
- House style is script-oriented: pipeline logic belongs in `scripts/`; `insight_forge/` stays a thin dispatcher.
- Crystallization behavior is declarative in `harness/rules.yaml`; changes there must keep the eval fixtures and contracts green.
- `--council` mode burns real LLM tokens and is gated to once per entry per 30 days — keep it expensive and explicit.
