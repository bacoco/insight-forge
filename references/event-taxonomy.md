# Event Taxonomy

Used by Stage 2 (Event Router) to classify each candidate event from the harvester.

## Skip filter (drop these BEFORE classification)

| Pattern | Why |
|---|---|
| Pure greetings, acknowledgments, "ok", "thanks" | No information |
| Clarifying questions with no answer in same session | No commitment |
| Pure formatting requests | No semantic content |
| Tool calls with `error: rate_limit` | Infrastructure noise |
| `<system-reminder>` blocks | Not user content |
| `<task-notification>` | Not user content |
| `[Request interrupted by user]` standalone | Surface as `pivot` only if next msg explains why |
| Skill loading injections (`Base directory for this skill:`) | Internal plumbing |
| Bash stdout/stderr longer than ~30 lines | Truncate or reference, don't extract |

If after the skip filter the session has zero candidates, log it as `events_extracted: 0` in `session_index.yaml` and move on. **Empty sessions are valid data** — they tell you no learning happened.

## Type classification (5 direct + 4 staged + 1 unknown)

### Direct types (write immediately to `trace/exploration_tree.yaml`)

These are journey facts. They happened. No interpretation required.

| Type | Trigger pattern in transcript | Required fields |
|---|---|---|
| `question` | User asks a what/why/how that doesn't get resolved in the same turn | `description`, `status: open` |
| `decision` | User chooses among alternatives explicitly ("let's go with X", "use Y instead of Z") OR an `ai-executed` choice that wasn't reverted | `choice`, `alternatives`, `evidence` |
| `experiment` | An attempt to verify something — running a test, benchmark, prototype | `hypothesis`, `result` (pending if not concluded in same session) |
| `dead_end` | An approach explicitly abandoned ("nope, that doesn't work", "scratch that") OR code that was written then reverted/deleted | `hypothesis`, `failure_mode`, `lesson`, `could_have_worked_if` |
| `pivot` | Mid-session direction change ("actually let's switch to...", "wait, different approach") | `from`, `to`, `trigger` |

### Staged types (write to `staging/observations.yaml`)

These are interpretations. They might be wrong. They wait for a closure signal.

| Type | Trigger pattern | Notes |
|---|---|---|
| `claim` | Falsifiable assertion of fact ("X is faster than Y", "Z always fails on Windows") | Must be falsifiable. "X is good" is not a claim. |
| `heuristic` | Imperative rule of thumb ("always use pytest, not unittest", "prefer composition over inheritance here") | Must be a *how*, not a *what*. |
| `concept` | A new term/abstraction the user introduces or relies on ("the auth-resolver pattern") | Often used implicitly across sessions. |
| `constraint` | Boundary condition the user expects to hold ("must run on Python 3.11+", "never write to /etc") | Often becomes a CLAUDE.md rule candidate. |

### Other

| Type | Notes |
|---|---|
| `unknown` | Use sparingly. If in doubt between two types, prefer `unknown` and resolve at next run. |

## Direct-vs-staged decision tree

```
Is the event a journey fact (it just happened)?
├── YES → Direct route to exploration_tree.yaml
│   └── Pick from: question, decision, experiment, dead_end, pivot
│
└── NO  → Is it interpretive (a generalization beyond the immediate fact)?
    ├── YES → Stage in observations.yaml
    │   └── Pick potential_type: claim, heuristic, concept, constraint
    │
    └── DOUBT → Stage as potential_type: unknown
```

**Heuristic for the borderline case**: if the event would still be true 6 months from now in a different project, it's interpretive (stage it). If it's only true here-and-now in this code, it's a journey fact (direct route).

## Provenance assignment (preview — see `provenance-reconstruction.md` for full rules)

| Tag | Post-hoc rule |
|---|---|
| `user` | Phrase appears verbatim in a user message |
| `ai-suggested` | First mentioned by the assistant, never explicitly endorsed by the user in the same session |
| `ai-executed` | Resulted in a successful tool_use (file write, command success) |
| `user-revised` | Pattern: assistant says X → user says "rather Y" → tag the suggestion as user-revised, with `original: X, revised: Y` |

## ID conventions

- `N{XX}` for tree nodes, sequential, never reused
- `O{XX}` for observations
- `C{XX}` for claims
- `H{XX}` for heuristics
- `D{XX}` for dead ends
- `K{XX}` for concepts
- `R{XX}` for constraints

Always read the existing file before allocating a new ID. The pipeline must be deterministic given the same input.

## Forensic bindings (mandatory when possible)

Every crystallized entry must have at least one binding:

| Type | Binding target |
|---|---|
| `claim` | `proof: [<evidence ref or session msg ref>]` |
| `heuristic` | `code_refs: [<file paths>]` |
| `dead_end` | `code_refs: [<files affected>]` + `avoid_signal` |
| `decision` | `evidence: [<refs>]` |
| `experiment` | `result: <text>` and ideally a code/config ref |

If no binding can be made, use `[pending]` + add a TODO comment. Better a flagged gap than a phantom claim.
