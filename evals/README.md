# Evals — regression harness

`run_evals.py` runs the pipeline against every fixture under `fixtures/`,
compares the resulting `.insight-forge/` state against `expected/<name>.expected.yaml`,
and reports headline metrics.

The single load-bearing metric is **`false_promotion_rate`**. Anything above 0 %
means the pipeline promoted something that shouldn't have crystallized — the
exact failure mode insight-forge exists to prevent.

## Run

```bash
python3 scripts/run_evals.py                       # all fixtures, human output
python3 scripts/run_evals.py --json                # machine-readable
python3 scripts/run_evals.py --fixture simple_success
```

Exit code is `0` only when every fixture passes.

## Layout

```
evals/
├── fixtures/            # Synthetic normalized.jsonl inputs
│   ├── simple_success.jsonl
│   ├── false_positive_instruction.jsonl
│   ├── abandoned_topic.jsonl
│   ├── empirical_resolution.jsonl
│   └── no_signal.jsonl
└── expected/            # One <name>.expected.yaml per fixture
    └── simple_success.expected.yaml
```

## Fixture format

Each fixture is a normalized JSONL stream — exactly what `extract_claude.py` /
`extract_codex.py` produce. Every session is bracketed by:

```jsonl
{"_marker": "session_start", "session_id": "...", "session_short": "...", "agent": "claude", "mtime": "2026-05-01T10:00:00", "size_kb": 4}
{"role": "user", "content": "...", "timestamp": "...", "session_id": "...", "session_short": "...", "agent": "claude"}
...
{"_marker": "session_end"}
```

Tool turns use `"role": "tool_use"` or `"role": "tool_result"`, with
`tool_name` and (for results) `tool_status`.

## Expected format

```yaml
crystallized:
  total: 1
  by_layer:
    heuristic: 1
    claim: 0
    dead_end: 0
    constraint: 0
    concept: 0
staged_only: 0
expected_signals:
  - verbal-affirmation     # one of: verbal-affirmation, empirical-resolution,
                           #         topic-abandonment, artifact-commitment
must_have_evidence_bundle: true
must_have_counter_evidence: true
notes: |
  Free-form rationale for future readers.
```

## Adding a new fixture

1. Create `fixtures/<name>.jsonl` with the synthetic transcript.
2. Create `expected/<name>.expected.yaml` with what the pipeline *should* do.
3. Run `python3 scripts/run_evals.py --fixture <name>`.
4. If it passes, commit. If it fails, the fixture is documenting a real
   pipeline bug — fix the pipeline, not the expected.

## Metrics

| Metric | What it measures |
|---|---|
| `false_promotion_rate` | Fraction of fixtures where actual crystallizations > expected. |
| `missed_promotion_rate` | Fraction where actual < expected. |
| `provenance_coverage` | Fraction of crystallized entries that have a non-empty evidence bundle. |
| `passed` / `failed` | Per-fixture pass count. |
