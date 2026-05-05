# Harness — portable rule spec

This directory holds the **classifier rule spec** as a portable, editable
artifact. Until now, Stage 2 of the pipeline (Event Router) lived as Python
regex inside `scripts/pipeline.py`. Here it lives as data:

```
harness/
├── rules.yaml      ← the spec
├── loader.py       ← load + execute rules
└── README.md       ← this file
```

## Why this exists

Two recent papers point in the same direction:

- **Tsinghua — *Natural-Language Agent Harnesses* (Pan et al., 2026):**
  harness control logic should live as a portable, editable artifact with
  explicit contracts and durable artifacts — not buried in controller code.
- **Stanford — *Meta-Harness* (Lee et al., 2026):** once harness behavior is
  data, an agentic proposer can optimize it end-to-end against evals.

`rules.yaml` is what externalization looks like for insight-forge: each
classification rule names its contract (which eval fixtures it must / must
not fire on), so any change to the spec is verifiable against measured
behavior — by `python3 scripts/run_evals.py --verify-contracts`.

## Rule format

```yaml
- id: R-CONSTRAINT-MUST-REQUIRES
  description: User constraint expressed via must/requires/doit/nécessite
  when:
    role: user
    content_matches_regex: "\\b(must|requires|doit|nécessite)\\s+\\S+"
  unless:
    any:
      - content_length_gt: 400
      - content_starts_with_imperative: true
  emit:
    route: staged
    type: constraint
    provenance: user
    confidence: medium
  contract:
    must_not_fire_on:
      - false_positive_instruction
```

### Predicate keys

| Key | Meaning |
|---|---|
| `role` | Match `user` / `assistant` / `tool_use` / `tool_result` / `system` |
| `tool_status` | Match `ok` / `error` (only on `tool_result`) |
| `content_matches_regex` | `re.search`, case-insensitive |
| `content_starts_with_regex` | `re.match`, case-insensitive |
| `content_contains_any_phrase_list` | Reference a phrase list under `phrase_lists:` |
| `content_length_lt` / `content_length_gt` | Numeric thresholds |
| `content_starts_with_imperative` | Boolean — does the message start with a task-imperative verb (issue #13)? |
| `matches_meta_work_prefix` | Boolean — assistant progress-narration filter |
| `previous_event: { ... }` | Sub-predicate evaluated against the previous event in the same session (uses prev_role / prev_content) |

### Predicate composition

`when:` is AND of all keys. Use `any:` (list) for OR; use `all:` (list) for
nested AND. Example:

```yaml
unless:
  any:
    - content_length_gt: 400
    - content_starts_with_imperative: true
```

### Emit shape

```yaml
emit:
  route: staged | direct
  type: claim | heuristic | dead_end | constraint | concept | decision | pivot | experiment | question
  provenance: user | ai-suggested | ai-executed | user-revised | unknown
  confidence: high | medium | low
  extra:                                  # optional, type-specific fields
    failure_mode: { from: content, max_chars: 300 }
    could_have_worked_if: not_explored
    tool_name: { from: tool_name }
```

`emit.extra` lets a rule populate type-specific fields without each
detector needing its own Python branch in `classify_and_route()`. Each
value is either:

- a literal (string / int / list / bool) — used as-is
- a mapping `{from: <attr_name>, max_chars: <int?>}` — read from the
  candidate event's named attribute, optionally truncated

### Contract block

```yaml
contract:
  must_fire_on: [fixture_stem, ...]      # rule MUST match an event in these
  must_not_fire_on: [fixture_stem, ...]  # rule MUST stay silent on these
```

`must_fire_on` checks at least one event in the fixture matches.
`must_not_fire_on` checks no event matches. Run
`python3 scripts/run_evals.py --verify-contracts` to enforce.

## Editing workflow

1. Open `rules.yaml`, change a regex or add a new rule.
2. Run `python3 scripts/run_evals.py --verify-contracts` — every contract
   line you wrote must hold.
3. Run `python3 scripts/run_evals.py` — all fixtures must pass.
4. Commit. The CI signal (when wired) is the same two commands.

If your change improves behavior on a real session but breaks a fixture,
the fixture is wrong — update it, with a note explaining why. If your
change breaks the contract metric (`false_promotion_rate`), the change is
wrong.

## What lives in code (not yet in rules.yaml)

The rule spec covers four classifier paths today:
- `R-DEADEND-TOOL-ERROR` — tool_result with status=error
- `R-HEURISTIC-ALWAYS-NEVER` — user "always X / never X" patterns
- `R-CONSTRAINT-MUST-REQUIRES` — user "must / requires / doit / nécessite"
- `R-CLAIM-ASSISTANT` — assistant comparative claims ("is faster than", etc.)

The remaining detectors (`pivot`, `decision`, `experiment`, `question`,
`dead_end via DEAD_END_PHRASES`) still live in `scripts/pipeline.py`. Each
either emits a unique `direct` event with its own extras (decision /
experiment / question / pivot) or relies on phrase-list matching that
isn't yet expressible in the predicate vocabulary. Migrating them is
incremental — `R-DEADEND-TOOL-ERROR` is the template (uses `emit.extra`
to populate `failure_mode` / `tool_name` / `could_have_worked_if`).

## The proposer

`scripts/propose_rules.py` closes the Stanford *Meta-Harness* loop:

1. Reads `rules.yaml` and the eval baseline.
2. For every fixture marked `known_gap: true` in `evals/expected/`,
   generates candidate mutations on its `target_rule` (currently:
   extending regex alternations with 1-3 leading tokens from the
   fixture's events).
3. Sandbox-evaluates each candidate — temp `rules.yaml`, full eval suite,
   contract verifier.
4. Scores `+1` per gap fixture closed, `-∞` for any regression or contract
   violation.
5. Writes the best candidate to `harness/proposals/<ts>.yaml` — never
   edits `rules.yaml` directly.

```bash
# See what mutations the proposer would suggest, without writing files
python3 scripts/propose_rules.py --dry-run

# Generate proposal files
python3 scripts/propose_rules.py

# Restrict to one gap
python3 scripts/propose_rules.py --target-fixture french_heuristic
```

The v1 proposer is deterministic. The mutation generator is the swappable
seam — an LLM-based generator can replace it without touching the
sandboxing or scoring code. See `harness/proposals/README.md` for the
proposal file format and how to apply one.

## Marking a known gap

Add to `evals/expected/<fixture>.expected.yaml`:

```yaml
known_gap: true
target_rule: R-HEURISTIC-ALWAYS-NEVER
```

The regression eval will skip this fixture (it appears as `[GAP]` in the
output). The proposer treats it as the optimization target. When a
proposal is applied, remove these two fields and the regression eval
starts enforcing the closure.
