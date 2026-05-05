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
```

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

The rule spec covers the three classifier paths whose behavior is regex-
shaped: `R-HEURISTIC-ALWAYS-NEVER`, `R-CONSTRAINT-MUST-REQUIRES`,
`R-CLAIM-ASSISTANT`. The remaining detectors (dead_end, pivot, decision,
tool_use experiment, question) still live in `scripts/pipeline.py` because
each emits unique extra fields the current schema doesn't model. Migrating
them is mechanical once the schema grows an `extra:` clause — left for a
future PR so this one stays small and reviewable.

## Why no agentic optimizer yet

Stanford Meta-Harness needs three things to optimize a harness:

1. ✅ Harness as data — `rules.yaml`
2. ✅ Eval contracts — `evals/expected/*.yaml` + `--verify-contracts`
3. ❌ Proposer that suggests rule edits and is rewarded by eval delta

Building (3) without (1) and (2) is fantasy. With (1) and (2) in place,
(3) is a straight engineering task — not in scope for this PR.
