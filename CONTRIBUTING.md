# Contributing

Thanks for considering a contribution. The project's design — *conservative
by default, every promotion verifiable, no auto-edits* — sets a clear bar
for what changes can ship.

## Setup

```bash
git clone https://github.com/bacoco/insight-forge
cd insight-forge

python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Requires Python ≥ 3.10. `pyyaml`, `pytest`, and `jsonschema` come as part
of the `[dev]` extras.

## The four quality gates

Every change must pass these four gates (CI enforces all of them on every PR):

```bash
# 1. Regression evals — fixtures + signal counts + provenance
insight-forge eval

# 2. Harness contracts — every rule's must_fire_on / must_not_fire_on holds
insight-forge eval --verify-contracts

# 3. Unit tests — YAML fallback, predicates, schema, contracts, CLI
pytest

# 4. Evidence traceability — every quote is a substring of its source
insight-forge validate-evidence --evals
```

If you can't get all four green locally, you can still open a PR — CI will
tell you exactly which gate fails on the matrix (Python 3.10 / 3.11 / 3.12).

## Common contribution patterns

### Adding an eval fixture

Most behavior contracts live as pairs under `evals/`:

1. Create `evals/fixtures/<name>.jsonl` — synthetic normalized JSONL
   (one event per line, bracketed by `_marker: session_start` / `session_end`).
   See `evals/README.md` for the format.

2. Create `evals/expected/<name>.expected.yaml` — what should and shouldn't
   crystallize. Optional fields:
   - `known_gap: true` — a fixture the proposer should target. Skipped from
     regression but visible in output.
   - `target_rule: R-...` — the rule the proposer should mutate.

3. Run `insight-forge eval --fixture <name>`. Fix the pipeline if the
   fixture documents real behavior; fix the expected if you mis-specified.

Never write an `expected.yaml` to match a buggy pipeline.

### Adding or changing a classifier rule

Classifier rules live in `harness/rules.yaml`. Each rule has:
- `when:` — predicate (AND of keys, plus `any:` / `all:` composition)
- `unless:` — optional negative predicate
- `emit:` — what RoutedEvent to produce
- `contract:` — `must_fire_on` / `must_not_fire_on` fixture references

A rule whose contract fails fails CI. To add a rule:

1. Edit `harness/rules.yaml`.
2. Reference at least one positive and one negative fixture in `contract:`.
3. Run `insight-forge eval --verify-contracts`.
4. Run `pytest tests/test_contracts.py -v` to confirm.

The full rule schema and predicate vocabulary lives in
[`harness/README.md`](harness/README.md).

### Adding an evidence bundle field

The evidence schema is at `schemas/evidence_bundle.schema.json`. To extend it:

1. Edit the schema (additive changes only — never break existing bundles).
2. Update `scripts/pipeline.py:write_evidence_bundle()` to populate the field.
3. Add a unit test in `tests/test_evidence_schema.py`.
4. Run `insight-forge validate-evidence --evals` — every bundle in the eval
   suite must still validate.

If a field stores user-quoted text, also extend
`scripts/validate_evidence.py:verify_traceability()` to check it.

### Editing the YAML lite parser

The fallback YAML parser in `scripts/pipeline.py` is a critical path —
users without `pyyaml` installed depend on it round-tripping rules.yaml,
evidence bundles, and observation state correctly.

**Before any change**, run `pytest tests/test_yaml_loader.py -v`. If your
change is correct, all 17 tests still pass. If you need to add a new edge
case, add the test first, then make it pass.

## Pull request hygiene

- One PR = one concern. *"feat: thing X + chore: rename Y"* is two PRs.
- Commits are squashed on merge — your PR title becomes the commit message,
  so write it as a complete sentence.
- A PR description should answer: **what changed, why, and how was it tested**.
- Don't bump version numbers in PRs unless the PR is the release itself.

## Things we don't accept

- Auto-application of any proposal. The user is the only authority that
  modifies `CLAUDE.md` / `AGENTS.md` or `harness/rules.yaml`.
- LLM-only mutations without a deterministic baseline path.
- Removing a closure signal — adding new ones is fine, removing established
  ones changes the trust contract.
- Vague counter-evidence. The Devil's Advocate clause must be specific to
  the claim, not a phrase that's true regardless of project.

## Where to read next

- [`README.md`](README.md) — what the tool does and why
- [`docs/how-it-works.md`](docs/how-it-works.md) — algorithm walkthrough
- [`harness/README.md`](harness/README.md) — rule spec and predicate vocabulary
- [`evals/README.md`](evals/README.md) — fixture format
- [`harness/proposals/README.md`](harness/proposals/README.md) — proposer output format
