# Insight Forge

A cross-session, agent-agnostic learner for **Claude Code** and **Codex CLI**.

Reads JSONL session transcripts → extracts typed events → maintains a structured knowledge base under `.insight-forge/` → proposes (never auto-applies) updates to `CLAUDE.md` / `AGENTS.md`.

Adapted from the **Agent-Native Research Artifact (ARA)** methodology, with three twists:
- **Post-hoc**, not end-of-turn — it reads transcripts after sessions end
- **Cross-session** — sees the full project history, not just the current turn
- **Devil's Advocate baked in** — every cristallisation must justify a `counter_evidence` field, and a 5-attacker council mode lets you stress-test load-bearing claims

---

## Install

The skill is dual-target. Same files, two homes.

### Claude Code

```bash
# User-level (available in all projects)
cp -r insight-forge ~/.claude/skills/

# Or project-level
mkdir -p .claude/skills && cp -r insight-forge .claude/skills/
```

### Codex CLI

```bash
# User-level
cp -r insight-forge ~/.codex/skills/

# Or project-level
mkdir -p .codex/skills && cp -r insight-forge .codex/skills/
```

That's it. Same skill, both agents. No config needed.

---

## Use

The skill is **user-invocable only** — it never auto-fires. Trigger phrases:

- `/insight-forge`
- `consolide les sessions`
- `qu'a-t-on appris depuis la dernière fois`
- `cristallise les enseignements`
- `analyse les sessions précédentes`
- (and the equivalents in English — see `SKILL.md` for the full list)

In Claude Code or Codex CLI, just type one of these. The skill detects which agent you're on, scans the right transcript directory, and runs the pipeline.

### Modes

| Mode | What it does | Cost |
|---|---|---|
| `/insight-forge` | Default. Scan since `.last_run`, update knowledge base, generate proposal. | Cheap (no LLM in pipeline itself) |
| `/insight-forge --challenge` | 6-axis Devil's Advocate sweep over crystallized claims, prioritizing entries flagged `Déni` by the quadrant grid. | Cheap |
| `/insight-forge --council <id>` | Submit a single entry to 5 incompatible attackers + Procureur synthesis. | **Expensive (~6 LLM calls)** |
| `/insight-forge --evidence <id>` | Render a focused HTML annex showing only the sessions that fed entry `<id>`. | Cheap |
| `/insight-forge --rebuild` | Wipe `.insight-forge/` (after confirmation) and reprocess from scratch. | Cheap |
| `/insight-forge --since 2026-04-01` | Override `.last_run` and process from a specific date. | Cheap |

The `--council` mode is the only one that burns real LLM tokens beyond pipeline overhead. It's gated to one run per entry per 30 days unless `--force`. Use it on entries about to be copied into `CLAUDE.md` / `AGENTS.md`, or entries the proposal flagged `Déni`.

---

## What it produces

```
.insight-forge/
├── INSIGHTS.md                       # Root manifest
├── .last_run                         # Cursor for incremental scans
├── .cache/normalized.jsonl           # Pivot schema (regen each run)
├── logic/                            # Crystallized typed knowledge
│   ├── claims.md                     # Falsifiable assertions + counter-evidence
│   ├── heuristics.md                 # Implementation rules of thumb
│   ├── dead_ends.md                  # Failure modes + "could have worked if"
│   └── concepts.md                   # Formal definitions
├── trace/                            # Journey facts
│   ├── exploration_tree.yaml         # DAG of decisions/experiments/dead_ends/pivots
│   ├── session_index.yaml            # One entry per scanned session
│   └── pipeline_log.yaml             # Self-continuity log
├── staging/observations.yaml         # The crystallisation buffer
├── council/                          # Council session bundles (when --council ran)
│   └── C03-2026-05-03/               # One per (entry, date) tuple
│       ├── 00-target.md
│       ├── 01-falsificationniste.prompt.md ... 05-second-ordre.prompt.md
│       ├── 06-procureur.prompt.md
│       ├── attack-XX-*.md            # Sub-agent responses
│       ├── verdict.md                # Procureur synthesis
│       └── manifest.json
├── evidence/sessions.html            # iMessage-style annex (rendered on demand)
└── proposals/<date>.md               # Pending CLAUDE.md / AGENTS.md updates
```

`logic/`, `trace/`, and `staging/` are plain markdown + minimal YAML — diffable, greppable, copy-pastable.

`evidence/sessions.html` is a forensic side-channel: dark-mode aware, iMessage-style chat layout for verifying any claim against the actual transcripts.

`proposals/<date>.md` is what you actually consume each run — it's the hand-off back to your `CLAUDE.md` / `AGENTS.md`. Suggestions are grouped by **epistemic quadrant** (Ancrage / Brouillard / Déni) so you know which ones can be copy-pasted directly and which ones should go to `--council` first.

`council/` accumulates the verdicts of stress-tested entries — permanent record so you don't waste tokens re-running.

---

## How it works (the 3-stage pipeline)

```
┌──────────────────────┐    ┌────────────────┐    ┌─────────────────────┐
│  Context Harvester   │ -> │  Event Router  │ -> │  Maturity Tracker   │
│  (extract from       │    │  (classify +   │    │  (crystallize when  │
│   JSONL transcripts) │    │   route)       │    │   closure signals)  │
└──────────────────────┘    └────────────────┘    └─────────────────────┘
```

**Stage 1** scans `~/.claude/projects/<encoded-cwd>/*.jsonl` (Claude Code) OR `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` filtered by cwd (Codex), drops noise, and emits candidate events.

**Stage 2** classifies each candidate. **Journey facts** (decisions, experiments, dead_ends, pivots, questions) go directly to `trace/exploration_tree.yaml`. **Interpretive content** (claims, heuristics, concepts, constraints) goes to staging.

**Stage 3** walks `staging/observations.yaml` and crystallizes only when **at least one of four closure signals** fires:
1. **Topic abandonment** — N+ sessions idle without revisit
2. **Verbal affirmation** — explicit user endorsement
3. **Empirical resolution** — tool execution confirmed/refuted (with keyword overlap check)
4. **Artifact commitment** — code/config now depends on it

**Default to non-promotion.** Premature crystallisation is the failure mode this design exists to prevent.

Each crystallisation must produce a `counter_evidence` field (Devil's Advocate clause). The pipeline runs a hedging-detection lint to reject vacuous template phrases. If no concrete counter can be articulated, it's tagged `not_explored` and surfaced as a warning in the run summary.

---

## Architecture

```
                    ┌─── extract_claude.py ───┐
                    │  (~/.claude/projects/)  │
                    │  format Anthropic       │
                    └──────────┬──────────────┘
                               │
                               ▼
                    ┌──────────────────────────┐
                    │  normalized.jsonl        │ ← shared pivot schema
                    │  (role/content/tool/     │
                    │   timestamp/...)         │
                    └──────────┬───────────────┘
                               │
                               ▼
              ┌────────────────────────────────────┐
              │  pipeline.py (agent-agnostic)      │
              │  Harvester → Router → Maturity     │
              │  + Devil's Advocate at promotion   │
              └────────────────────────────────────┘
                               ▲
                               │
                    ┌──────────┴──────────────┐
                    │   extract_codex.py      │
                    │  (~/.codex/sessions/)   │
                    │  format OpenAI          │
                    │  cwd from <env_ctx>     │
                    └─────────────────────────┘
```

The two extractors absorb agent-specific quirks (Claude Code's encoded-cwd directories vs Codex's date-sharded rollouts) and emit the same normalized schema. The pipeline is identical for both.

---

## Files

```
insight-forge/
├── SKILL.md                            # Entry point — describes triggers, schemas, rules
├── README.md                           # This file
├── scripts/
│   ├── extract_claude.py               # Claude Code transcript reader
│   ├── extract_codex.py                # Codex CLI rollout reader
│   ├── pipeline.py                     # ARA core (Harvester / Router / Maturity)
│   ├── propose_claude_md.py            # Generate diff proposal
│   ├── render_evidence.py              # iMessage HTML annex
│   └── council.py                      # 5-attacker council preparator
├── references/
│   ├── event-taxonomy.md               # Type classification + filter rules
│   ├── crystallization-rules.md        # 4 closure signals + procedure
│   ├── provenance-reconstruction.md    # Post-hoc provenance inference
│   ├── contradiction-protocol.md       # Conflict surfacing
│   ├── devils-advocate.md              # Counter-clauses + hedging detection + 6-axis sweep
│   ├── known-unknown-mapping.md        # Rumsfeld grid (Ancrage/Brouillard/Déni/Abîme)
│   ├── council-protocol.md             # 5-attacker council protocol
│   ├── codex-format.md                 # Codex JSONL spec
│   └── claude-code-format.md           # Claude Code JSONL spec
└── templates/
    └── imessage_template.html          # Forensic HTML chrome
```

---

## Manual / scripted use

You don't need the skill harness — you can run the scripts directly:

```bash
# Extract Claude Code sessions for current project
python3 scripts/extract_claude.py --project $(pwd) --out /tmp/normalized.jsonl

# Or Codex
python3 scripts/extract_codex.py --project $(pwd) --out /tmp/normalized.jsonl

# Run the ARA pipeline
python3 scripts/pipeline.py --input /tmp/normalized.jsonl --forge-dir .insight-forge

# Generate the proposal
python3 scripts/propose_claude_md.py --forge-dir .insight-forge

# Render the HTML annex
python3 scripts/render_evidence.py --forge-dir .insight-forge --input /tmp/normalized.jsonl

# Prepare a council session (LLM orchestration is then the agent's job)
python3 scripts/council.py --entry C03 --forge-dir .insight-forge
```

This is also useful for CI — you could run pipeline + propose nightly on a developer's machine to surface what's been learned that day.

---

## Limitations

- **Codex sessions are sharded by date, not project.** The cwd filter relies on `<environment_context>` blocks in the first user message — sometimes flaky.
- **Auto-compaction loses messages.** The pipeline tolerates gaps but won't extract from compacted summaries.
- **30-day retention on Claude Code by default** — old sessions get auto-deleted. The pipeline only sees what's still on disk.
- **Subagents excluded by default.** Use `--include-subagents` if you want them, but the signal-to-noise ratio is poor.
- **Provenance is reconstructed, not captured.** Post-hoc inference is heuristic — confidence flags surface uncertainty.
- **Counter-evidence generation is template-based** in this baseline (with hedging-lint to reject vacuous outputs). The `--council` mode is where real attacks come from.
- **Council requires the agent to orchestrate sub-agents.** The Python preparator is deterministic; the LLM calls are made by Claude Code (`Task` tool) or Codex CLI (sub-agent system). Standalone CLI use of `--council` produces prompts ready for any orchestrator.

See `SKILL.md` § "Failure modes to expect" for the full list.

---

## Why does this exist?

CLAUDE.md / AGENTS.md tend to become graveyards of overconfident claims that nobody refutes. Long-running projects accumulate contradictions silently. Insight Forge is the smallest intervention against that rot:

1. Crystallize only on closure signals (no counter-based maturity)
2. Force a counter-evidence clause at every promotion, with hedging lint
3. Tag entries by epistemic quadrant (`Ancrage` / `Brouillard` / `Déni`) so the user knows what to trust
4. For load-bearing entries: 5 incompatible attackers in `--council` mode
5. Surface contradictions instead of silently merging
6. Keep the audit trail — staged → cristallized, never overwritten

It's specifically designed to be **boring and conservative**. False positives (overconfident promotions) are worse than false negatives (things that stay in staging too long).

---

## Sources & credits

This skill is a synthesis. The methodology is not original — it adapts and combines several existing ideas. Explicit attribution by component:

### Methodology — ARA (the spine)

**[Agent-Native Research Artifact](https://github.com/Orchestra-Research/Agent-Native-Research-Artifact)** by [Orchestra Research](https://github.com/Orchestra-Research)

- The 3-stage pipeline (Context Harvester → Event Router → Maturity Tracker)
- The "stage interpretive content, route journey facts directly" dichotomy
- The 4 closure signals (topic-abandonment, verbal-affirmation, empirical-resolution, artifact-commitment)
- "Default to non-promotion" as the operating principle
- The forensic bindings concept (claim→proof, heuristic→code)
- The 4-tag provenance system (user / ai-suggested / ai-executed / user-revised)

What insight-forge changes from ARA: post-hoc instead of end-of-turn, cross-session instead of per-turn, agent-agnostic (Claude Code + Codex CLI), provenance reconstructed from transcript instead of captured live.

### Forensic UI — creation-autopsy

**[Sandjab/skills-that-kill](https://github.com/Sandjab/skills-that-kill)**, specifically the `creation-autopsy` skill

- The iMessage-style HTML annex layout
- Cross-platform JSONL path resolution (Windows `D--DEV-foo` vs POSIX `-Users-jp-foo` encoding)
- "Don't speculate, only verbatim citations" as a rendering constraint
- The `<system-reminder>` / `<task-notification>` filter rules

### Codex format research — codex-history-list

**[shinshin86/codex-history-list](https://github.com/shinshin86/codex-history-list)**

- The pattern for scanning `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
- Filtering by cwd via `<environment_context>` block parsing
- Reference implementation for the date-sharded session structure

### Native CLI knowledge — `/insights`

**Claude Code's built-in `/insights` command** (Anthropic, ships with Claude Opus 4.6+)

- Concept: caching facets of session history for fast queries
- Auto-generation of CLAUDE.md rules from repeated user instructions
- Insight-forge does NOT replace `/insights` — it builds a structured layer on top.

### Epistemic grid — connu-inconnu

**`connu-inconnu` skill** (provided by user, see local copy)

Adapts the Rumsfeld matrix (Known Knowns / Known Unknowns / Unknown Knowns / Unknown Unknowns) into the 4 quadrants Ancrage / Brouillard / Déni / Abîme.

What insight-forge takes:
- The orthogonal epistemic axis applied to crystallized entries (`references/known-unknown-mapping.md`)
- The hedging detection lint rules ("phrases that stay true regardless of project = generic = remove") applied to our own counter-evidence outputs (`references/devils-advocate.md`)
- The 6-axis systematic sweep (accessibility, performance, security, maintenance, legal, organizational) as the search frame for `--challenge` mode
- The "access clause" for epistemic honesty when counter-evidence requires unavailable information

### Adversarial method — devil-council

**`devil-council` skill** (provided by user, see local copy)

A radicalized variant of LLM Council with 5 structurally incompatible attackers (Falsificationniste / Pré-mortem / Inverseur / Contraintes-First / Second-Ordre) + Procureur synthesis.

What insight-forge takes:
- The 5 attackers verbatim, repurposed for stress-testing crystallized entries
- The "irrevocable reasoning constraints" framing (not personas — methods locked one-sidedly)
- The 3-tension structure (Falsificationniste vs Inverseur, Pré-mortem vs Second-Ordre, Contraintes-First as concrete anchor)
- The Procureur output structure (Convergence / Divergences / Angles morts collectifs / Diagnostic / Point de rupture)
- The "spawn in parallel" rule (sequential = contamination)

What insight-forge changes: the orchestration model. The Python preparator (`scripts/council.py`) writes prompts deterministically; the agent (Claude Code or Codex) does the LLM calls via its native sub-agent system. This makes `--council` testable and SDK-free.

### Skill anatomy — Anthropic

**[Anthropic skill-creator](https://github.com/anthropics/skills)**

- The SKILL.md frontmatter format
- The `description: ` field as triggering mechanism
- The progressive disclosure pattern (SKILL.md as entry point, `references/` for depth, `scripts/` for execution)
- "Make descriptions a little pushy" — explicit triggers in the description

### Repo

This implementation is intended to be published at `https://github.com/bacoco/insight-forge`. The combination is MIT-licensed; individual sources retain their original licenses.

---

## Idea provenance table

| Component | Source | What we kept | What we changed |
|---|---|---|---|
| 3-stage pipeline | ARA | Full | Made post-hoc, cross-session |
| 4 closure signals | ARA | Full | Reconstruct closure signals from transcript instead of detecting live |
| Provenance tagging | ARA | 4-tag system | Reconstruction rules (Rule 1-5 in `provenance-reconstruction.md`) |
| Dead-end as first-class | ARA | Concept | Added `could_have_worked_if` Devil's Advocate clause |
| iMessage HTML | creation-autopsy | Layout, filter rules, dark mode | Adapted for entry-focused rendering (`--evidence C03`) |
| Codex JSONL parsing | codex-history-list | cwd filter strategy | Generalized to event normalization |
| Quadrant grid | connu-inconnu | 4-quadrant matrix | Applied to crystallized entries instead of project briefs |
| Hedging lint | connu-inconnu | "Phrases that stay true regardless of topic = bad" | Applied to counter_evidence outputs |
| 6-axis sweep | connu-inconnu | Full | Used as `--challenge` search frame |
| 5 attackers | devil-council | Verbatim constraints | Targets a single crystallized entry instead of fresh proposal |
| Procureur synthesis | devil-council | 5-section structure | Same |
| Parallel orchestration | devil-council | "Spawn in parallel, never sequential" | Delegated to agent's native sub-agent system |

---

## License

MIT for this combination. Individual source skills/methodologies retain their licenses — see their respective repos.
