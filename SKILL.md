---
name: insight-forge
description: "ARA-style cross-session learner for Claude Code AND Codex CLI. Reads JSONL session histories from ~/.claude/projects/ (Claude Code) or ~/.codex/sessions/ (Codex CLI), extracts research-significant events through a 3-stage pipeline (Context Harvester → Event Router → Maturity Tracker), maintains a typed knowledge base under .insight-forge/ (claims, heuristics, dead_ends, exploration_tree), and proposes diffs for CLAUDE.md / AGENTS.md. USER-INVOCABLE ONLY. MANDATORY TRIGGERS (skill must NEVER auto-fire outside these exact formulations): '/insight-forge', 'insight-forge', 'forge insights', 'forge l'insight', 'consolide les sessions', 'consolide les insights', 'mets à jour les insights', 'analyse les sessions précédentes', 'que retient-on des dernières sessions', 'qu'a-t-on appris depuis la dernière fois', 'cristallise les enseignements'. Do NOT trigger on vague paraphrases, git history questions, current-conversation summaries, or any request without one of these exact formulations."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Insight Forge

A cross-session, post-hoc, agent-agnostic learner for coding agents.
Reads session transcripts → extracts typed events → maintains a structured knowledge base
→ proposes (never auto-applies) updates to `CLAUDE.md` / `AGENTS.md`.

The design is adapted from the **Agent-Native Research Artifact (ARA)** methodology,
specifically its `research-manager` skill. Key differences from the original:

- **Post-hoc, not end-of-turn.** Operates on JSONL transcripts after sessions end.
- **Cross-session.** Sees the full history, not just the current turn.
- **Agent-agnostic.** Same pipeline runs over Claude Code OR Codex CLI sessions.
- **Provenance reconstructed**, not captured live (see `references/provenance-reconstruction.md`).
- **Devil's Advocate baked in.** Every cristallisation must justify a `counter_evidence` field.

## When This Skill Runs

**USER-INVOCABLE ONLY.** Never auto-fire. The triggers in the YAML description are exhaustive — anything outside them, do not trigger. In doubt, do not trigger.

This skill writes to a structured knowledge base under `.insight-forge/` in the current project. It can also propose a diff to `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex CLI), but **never writes to those files directly** — proposals land in `.insight-forge/proposals/` for the user to review and apply manually.

## The 3-Stage Pipeline (ARA-derived)

```
┌──────────────────────┐    ┌────────────────┐    ┌─────────────────────┐
│  Context Harvester   │ -> │  Event Router  │ -> │  Maturity Tracker   │
│  (extract from       │    │  (classify +   │    │  (crystallize when  │
│   JSONL transcripts) │    │   route)       │    │   closure signals)  │
└──────────────────────┘    └────────────────┘    └─────────────────────┘
```

### Stage 1 — Context Harvester
Scans the JSONL files of sessions newer than `.insight-forge/.last_run` (or all sessions on first run). Filters out noise (system-reminders, hooks, bash-input, skill-loading injections — see `references/codex-format.md` and `references/claude-code-format.md` for the exact filter rules). Outputs a flat list of candidate events with raw context.

### Stage 2 — Event Router
For each candidate, classifies it and tags provenance per `references/event-taxonomy.md` and `references/provenance-reconstruction.md`. The dichotomy: **journey facts go direct, interpretive claims go staged**. Direct events (decisions, experiments, dead_ends, pivots, questions) write immediately to `.insight-forge/trace/exploration_tree.yaml`. Interpretive events (claims, heuristics, concepts, constraints) go to `.insight-forge/staging/observations.yaml`.

### Stage 3 — Maturity Tracker
Walks `staging/observations.yaml` and decides which staged observations are mature. Cristallisation requires **at least one** of four closure signals (per `references/crystallization-rules.md`):

1. **Topic abandonment** — N+ sessions idle without revisit
2. **Verbal affirmation** — explicit user endorsement in transcript
3. **Empirical resolution** — tool execution confirmed/refuted the observation
4. **Artifact commitment** — code/config now depends on the observation

**Default to non-promotion.** Premature crystallisation pollutes the knowledge base and is the failure mode this design exists to prevent.

When promoting, also generate a `counter_evidence` field — the Devil's Advocate clause (see `references/devils-advocate.md`). If no counter-evidence can be articulated, mark as `counter_evidence: not_explored` and treat as warning.

## Per-Run Procedure

```
1. Detect agent: presence of ~/.claude/projects/ → claude, ~/.codex/sessions/ → codex.
   If both: ask user which to scan, or scan both with separate runs.
2. Resolve project cwd → JSONL discovery:
   - Claude Code: scripts/extract_claude.py (uses cwd-encoded directory)
   - Codex CLI:    scripts/extract_codex.py (filters by <environment_context> cwd)
3. Read .insight-forge/.last_run (or initialize if missing).
4. Filter: sessions modified after .last_run.
5. Normalize: scripts/normalize.py → .insight-forge/.cache/normalized.jsonl
6. Pipeline: scripts/pipeline.py → updates ARA structure
7. Propose: scripts/propose_claude_md.py → .insight-forge/proposals/<date>.md
8. Update .last_run.
9. Print one-line summary:
   [insight-forge] Scanned N sessions: 3 dead_ends added, 2 claims crystallized,
   1 contradiction flagged, 5 observations staged, proposals/2026-05-03.md ready.
```

## ARA Directory Structure (under `.insight-forge/`)

```
.insight-forge/
├── INSIGHTS.md                       # Root manifest + layer index (~200 tokens)
├── .last_run                         # ISO timestamp + last-processed session_id
├── .cache/
│   ├── normalized.jsonl              # Pivot schema, regen on each run
│   └── facets.json                   # Optional: read /insights cache if available
├── logic/                            # What & Why (crystallized only)
│   ├── claims.md                     # Falsifiable assertions + proof refs
│   ├── heuristics.md                 # Implementation tricks + rationale + sensitivity
│   ├── dead_ends.md                  # First-class — failure modes + lessons
│   └── concepts.md                   # Formal definitions
├── trace/                            # Journey (direct routing)
│   ├── exploration_tree.yaml         # DAG: decisions/experiments/dead_ends/pivots
│   ├── session_index.yaml            # One entry per scanned session
│   └── pipeline_log.yaml             # Self-continuity: pipeline's own decisions
├── staging/
│   └── observations.yaml             # The crystallisation buffer
├── evidence/
│   ├── README.md
│   └── sessions.html                 # iMessage-style annex (rendered on demand)
└── proposals/
    ├── claude_md_diff_<date>.md      # Or AGENTS.md depending on agent
    └── README.md
```

## Schemas

### Exploration Tree Node — `trace/exploration_tree.yaml`

```yaml
tree:
  - id: N01
    type: question | decision | experiment | dead_end | pivot
    title: "{short title}"
    provenance: user | ai-suggested | ai-executed | user-revised
    timestamp: "YYYY-MM-DDTHH:MM"
    session_id: "{8-char prefix}"
    # type-specific fields:
    description: >    # question
    choice: >         # decision
    alternatives: []  # decision
    evidence: []      # decision, experiment
    result: >         # experiment
    hypothesis: >     # dead_end
    failure_mode: >   # dead_end
    lesson: >         # dead_end
    could_have_worked_if: >  # dead_end — Devil's Advocate clause
    from: ""          # pivot
    to: ""            # pivot
    trigger: ""       # pivot
    status: open | resolved | unresolved
    children: []
    also_depends_on: [N{XX}]  # cross-edges
```

### Claim — `logic/claims.md`

```markdown
## C{XX}: {title}
- **Statement**: {falsifiable assertion}
- **Status**: hypothesis | supported | weakened | refuted | revised
- **Provenance**: user | ai-suggested | user-revised
- **Crystallized via**: topic-abandonment | verbal-affirmation | empirical-resolution | artifact-commitment
- **Counter-evidence**: {what would refute this — Devil's Advocate} | not_explored
- **Falsification criteria**: {what would disprove this}
- **Proof**: [{evidence refs or "pending"}]
- **Dependencies**: [C{YY}, ...]
- **Tags**: {comma-separated}
- **From staging**: O{XX}
- **Sessions**: [{session_id 8-char prefixes}]
```

### Heuristic — `logic/heuristics.md`

```markdown
## H{XX}: {title}
- **Rule**: {short imperative}
- **Rationale**: {why it works}
- **Provenance**: user | ai-suggested | user-revised
- **Crystallized via**: {closure signal}
- **Sensitivity**: low | medium | high
- **Code refs**: [{file paths or "pending"}]
- **Counter-cases**: {when does this NOT apply — Devil's Advocate}
- **From staging**: O{XX}
- **Sessions**: [{session_id prefixes}]
```

### Dead End — `logic/dead_ends.md`

```markdown
## D{XX}: {title}
- **Hypothesis tested**: {what was tried}
- **Failure mode**: {how it broke}
- **Lesson**: {takeaway, single sentence}
- **Could have worked if**: {Devil's Advocate clause — what missing piece could have rescued this}
- **Provenance**: user | ai-suggested | ai-executed | user-revised
- **Code refs**: [{file paths affected}]
- **Sessions**: [{session_id prefixes}]
- **Avoid signal**: {phrase that should make Claude/Codex avoid this in future}
```

### Observation — `staging/observations.yaml`

```yaml
observations:
  - id: O{XX}
    timestamp: "YYYY-MM-DDTHH:MM"
    provenance: user | ai-suggested | ai-executed | user-revised
    content: "{distilled observation}"
    context: "{what was happening in the session}"
    potential_type: claim | heuristic | concept | constraint | architecture | dead_end | unknown
    bound_to: [N{XX}, ...]
    promoted: false
    promoted_to: null
    crystallized_via: null
    stale: false
    last_referenced: "YYYY-MM-DD"
    session_id: "{8-char prefix}"
```

### Session Index — `trace/session_index.yaml`

```yaml
sessions:
  - id: "{8-char prefix}"
    full_id: "{full UUID}"
    agent: claude | codex
    date: "YYYY-MM-DD"
    cwd: "{project path}"
    turn_count: {N}
    file_size_kb: {N}
    summary: "{one-line synthesis}"
    events_extracted: {N}
    observations_staged: {N}
    crystallizations: {N}
    contradictions_flagged: {N}
```

### Pipeline Log — `trace/pipeline_log.yaml`

A few lines per run explaining the pipeline's organisational decisions. Cheap on tokens, prevents organisational drift across runs.

```yaml
runs:
  - run_id: "YYYY-MM-DDTHH:MM"
    sessions_processed: [{session_id prefixes}]
    notes:
      - "Staged O07 as potential_type: heuristic — it's a how, not a what."
      - "Did NOT crystallize O05 despite affirmation-like language: user said 'maybe'."
      - "Routed N12 as dead_end — code was abandoned mid-run, never revisited."
```

## Initialization (if `.insight-forge/` does not exist)

Only initialize on a triggered run. Don't ask unprompted.

```bash
mkdir -p .insight-forge/{logic,trace,staging,evidence,proposals,.cache}
```

Then seed:
- `INSIGHTS.md` — root manifest (infer project from `cwd` and any existing `CLAUDE.md`/`AGENTS.md`)
- `trace/session_index.yaml` — `sessions: []`
- `trace/exploration_tree.yaml` — `tree: []`
- `trace/pipeline_log.yaml` — `runs: []`
- `staging/observations.yaml` — `observations: []`
- `logic/claims.md` — `# Claims`
- `logic/heuristics.md` — `# Heuristics`
- `logic/dead_ends.md` — `# Dead Ends`
- `logic/concepts.md` — `# Concepts`
- `evidence/README.md` — `# Evidence Index`
- `proposals/README.md` — `# Proposals`
- `.last_run` — empty

Add `.insight-forge/` to `.gitignore` only if user requests — by default, the user may want to version it.

## Run Modes

### `/insight-forge` (default)
Full pipeline: scan since `.last_run` → extract → route → mature → propose. End with one-line summary and pointer to `proposals/<date>.md`.

### `/insight-forge --challenge`
**Non-tautological** Devil's Advocate sweep over already-crystallized claims. For each `status: supported` claim, run the **6-axis projection** (accessibility, performance, security, maintenance, legal, organizational — see `references/devils-advocate.md`) and search NEW sessions for evidence on each axis. Prioritize entries the quadrant mapping flags as `Déni`. Does not modify claims directly — flags only.

### `/insight-forge --council <entry_id>`
The big one. Submits a single cristallized entry to **5 structurally incompatible attackers**: Falsificationniste, Pré-mortem, Inverseur, Contraintes-First, Second-Ordre. Then a Procureur synthesizes the verdict. See `references/council-protocol.md` for the protocol.

Workflow:
1. `scripts/council.py --entry C03` writes 6 prompt files into `.insight-forge/council/C03-<date>/`
2. **The agent (Claude Code or Codex CLI)** reads `council/C03-<date>/README.md` and spawns 5 sub-agents IN PARALLEL via its native sub-agent system (`Task` tool for Claude Code, sub-agent for Codex)
3. Each sub-agent's response is saved to `attack-XX-*.md`
4. The agent fills the placeholders in `06-procureur.prompt.md` with the 5 responses, runs a 6th call, saves the result to `verdict.md`
5. The user reads `verdict.md` and decides whether to update the entry

Hard cost-discipline: one council per entry per 30 days unless `--force`. The `--council all` syntax is intentionally absent — single entry only.

### `/insight-forge --evidence <entry_id>`
Render a focused HTML iMessage view of just the sessions that fed a specific claim/heuristic/dead_end. Output to `evidence/sessions-<id>.html`.

### `/insight-forge --rebuild`
Discard `.insight-forge/` (after confirmation prompt) and reprocess everything from scratch. Useful when filter rules or schemas evolve.

### `/insight-forge --since YYYY-MM-DD`
Override `.last_run` and process from a specific date. Useful for backfill.

## Rules

1. **USER-INVOCABLE ONLY.** Never run on auto-pilot. Verify a trigger phrase appeared in the user's message before proceeding.
2. **Never fabricate events.** Only log what actually happened in the JSONL.
3. **Stage by default.** Claims, heuristics, concepts, constraints, architecture statements pass through staging.
4. **Never crystallize without a closure signal.** No counters, no LM-judged maturity — abandonment / affirmation / resolution / commitment only.
5. **Never auto-upgrade provenance.** `ai-suggested` stays until verbatim user affirmation.
6. **Never silently overwrite contradictions.** Flag both, append unresolved decision node, defer.
7. **Always read existing files first.** Get correct next IDs, avoid duplicates.
8. **Establish forensic bindings.** claim→proof, heuristic→code, decision→evidence. Use `[pending]` + TODO if not yet bindable.
9. **Append, never overwrite.** New entries only; status updates use Edit on the specific field.
10. **Devil's Advocate always.** Every crystallisation must produce `counter_evidence` (or `not_explored` flagged).
11. **Never auto-edit `CLAUDE.md` or `AGENTS.md`.** Only write to `.insight-forge/proposals/`.
12. **Be terse in summaries.** One line per run, factual.
13. **Filtered transcripts only.** See `references/codex-format.md` and `references/claude-code-format.md` for the noise filter rules.
14. **Cross-platform paths.** Use `~` resolution and Path operations — Windows `D:\` vs POSIX `/Users/`.

## Reference files

- `references/event-taxonomy.md` — kind classification, direct-vs-staged decision tree, skip filter
- `references/crystallization-rules.md` — 4 closure signals + procedure + contradiction trigger
- `references/provenance-reconstruction.md` — post-hoc rules to infer provenance from transcript
- `references/contradiction-protocol.md` — what to do when an event contradicts staged/cristallized
- `references/devils-advocate.md` — required Devil's Advocate clauses, hedging detection lint, the 6-axis sweep, and the non-tautological `--challenge` mode
- `references/known-unknown-mapping.md` — Rumsfeld matrix as orthogonal grid (Ancrage/Brouillard/Déni/Abîme), routing logic for proposals and challenge prioritization
- `references/council-protocol.md` — 5-attacker protocol for `--council` mode
- `references/codex-format.md` — Codex CLI JSONL spec + filter rules
- `references/claude-code-format.md` — Claude Code JSONL spec + filter rules

## Scripts

- `scripts/extract_claude.py` — locate `~/.claude/projects/<encoded-cwd>/*.jsonl`, output filtered events
- `scripts/extract_codex.py` — locate `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, filter by `<environment_context>` cwd
- `scripts/normalize.py` — convert either format to a common pivot schema
- `scripts/pipeline.py` — Harvester → Router → Maturity, the ARA core
- `scripts/render_evidence.py` — iMessage-style HTML annex (adapted from creation-autopsy)
- `scripts/propose_claude_md.py` — generate the diff proposal
- `scripts/council.py` — prepare a 5-attacker council session for a single entry (no LLM calls itself; agent orchestrates)

## Compatibility

The skill is dual-target. Place at:
- **Claude Code**: `~/.claude/skills/insight-forge/` (user) or `<project>/.claude/skills/insight-forge/` (project)
- **Codex CLI**: `~/.codex/skills/insight-forge/` (user) or `<project>/.codex/skills/insight-forge/` (project)

Trigger phrases work identically. The agent detection step at the start of the pipeline auto-routes to the right extractor.

## Failure modes to expect

- **Codex sessions sharded by date, not project.** Filtering by cwd is approximate (lives in `<environment_context>`). Some sessions might be missed if the cwd block was malformed.
- **Auto-compaction.** Long Claude Code sessions get compacted — some messages will be missing. The pipeline must tolerate gaps.
- **Renamed/moved projects.** Old sessions stored under the old encoded-cwd are unreachable unless user provides a hint.
- **Subagents.** Subagent transcripts are excluded by default (signal-to-noise too low).
- **Staging that never crystallizes.** Observations can sit forever in staging if no closure signal fires. The `stale: true` flag after 14 days surfaces them at next run for triage.
