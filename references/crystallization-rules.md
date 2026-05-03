# Crystallization Rules

Stage 3 (Maturity Tracker) walks `staging/observations.yaml` and decides which staged observations to promote.

**Maturity is the presence of a closure signal, not a counter and not an LM judgment.**

## The 4 closure signals

A staged observation `O{XX}` crystallizes when **at least one** of these is satisfied. Each signal has a strict definition adapted for post-hoc transcript analysis.

### 1. Topic abandonment

The observation's topic has had no events in the last `k=5` sessions across the full session_index, AND is not referenced in any `open_threads` of recent session_index entries.

How to check:
- Identify the observation's topic via its `bound_to` exploration nodes OR via the longest non-trivial noun phrase in `content`
- Search transcripts (or session_index summaries) of the last 5 processed sessions for that topic
- If absent → fire signal

**Be generous about what counts as a revisit.** False abandonment is worse than late abandonment — wait one more cycle.

### 2. Verbal affirmation

The user explicitly endorsed the observation in some session. Adoption must be **first-person**, in a user message, NOT in an assistant message.

Trigger phrases (English + French):
```
yes / oui
confirmed / confirmé
correct / exact / c'est ça
let's go with X / on part sur X
ship it
exactly / précisément
right / juste
go for it / vas-y
```

**Negative triggers** (these are NOT affirmations):
```
maybe / probably / peut-être / sans doute
silence / no response (silence is never affirmation)
```

How to check post-hoc:
- For each staged observation, find the assistant message that introduced the underlying claim
- Find the next user message in the same or following session
- Match against the trigger list (case-insensitive, accent-insensitive)

If the user phrased the affirmation differently from the assistant's wording, this also upgrades provenance: `ai-suggested` → `user-revised` (or `user` if the user reproduced the wording verbatim).

### 3. Empirical resolution

A tool execution in the observation's `bound_to` produced a result that confirmed or refuted the observation, AND the user commented on the result.

How to check:
- For each `bound_to` node of type `experiment`, look at its `result` field
- If the result aligns with the observation → crystallize as `claim` with `status: supported`
- If the result contradicts → **promote to `dead_end`, NOT to `claim`**, and copy the lesson
- The user comment requirement: there must be a user message after the result that engages with it (even just "good" or "ah ok"). Silence after a tool result is not resolution.

### 4. Artifact commitment

A downstream artifact now depends on the observation:
- A `decision` node cites it as evidence
- A config got fixed to a specific value the observation specifies
- Code was merged that depends on the observation
- A subsequent claim cites it as a premise

How to check:
- Search `trace/exploration_tree.yaml` for `evidence: [O{XX}]` references
- Search committed code (`git log -- <referenced files>`) for changes after the observation timestamp that align with the observation
- Search later staged observations for `dependencies: [O{XX}]` (becomes claim dependency on promotion)

## Crystallization procedure

When at least one signal fires for `O{XX}`:

1. Read O{XX}'s `content`, `context`, `potential_type`, `provenance`, `bound_to`
2. Allocate next ID for target layer (read target file first to find max existing ID)
3. Construct typed entry per schema in main `SKILL.md`
4. Carry forward `provenance`. Verbal-affirmation upgrades `ai-suggested` → `user-revised` (or `user` if verbatim). Other 3 signals do **not** upgrade provenance.
5. Add fields:
   - `Crystallized via: <signal>`
   - `From staging: O{XX}`
   - `Sessions: [<session_id 8-char prefixes that contributed>]`
6. **Devil's Advocate clause** (mandatory — see `devils-advocate.md`):
   - Generate `counter_evidence: <what would refute this>` OR mark `counter_evidence: not_explored` (warning surfaced at next run)
7. Establish forensic bindings (claim→proof, heuristic→code, decision→evidence). Use `[pending]` + TODO if a binding cannot be made now.
8. Update O{XX}: `promoted: true`, `promoted_to: <layer>:<id>`, `crystallized_via: <signal>`. **Do not delete the observation** — the trail from raw to typed is part of the audit record.

## Default to non-promotion

If no signal fires clearly, leave staged. Premature crystallization is the failure mode this design exists to prevent.

When in doubt:
- Prefer staging another cycle
- Prefer `unknown` over a guessed type
- Prefer `[pending]` bindings over invented references

## Stale flagging

A staged observation that has neither been promoted nor referenced for **14 days** (configurable) gets `stale: true`.

Stale observations are surfaced at the next pipeline run for the user to triage:
- Manually crystallize → user uses verbal-affirmation override
- Manually discard → user invokes `/insight-forge --discard O{XX}`
- Leave staged → re-flagged at next run

The pipeline never auto-discards stale observations.

## Contradiction trigger

If a new event from this run contradicts an already-staged or already-crystallized entry:

1. **Do not silently overwrite either entry.**
2. Append a `<!-- CONFLICT: see {other-id} -->` comment in markdown OR a `# CONFLICT: see {other-id}` line in YAML next to BOTH entries.
3. Append an `unresolved` `decision` node to `exploration_tree.yaml` referencing both, with provenance reflecting who introduced the contradiction (usually `ai-executed` if a tool result, or `user` if a new user statement).
4. Stop. Adjudication is the user's job at a future turn — surface the conflict in the run summary.

See `contradiction-protocol.md` for the full handling rules.
