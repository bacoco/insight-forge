# Insight Forge

![Insight Forge](assets/banner.jpg)

### Your AI sessions know more than you think.

---

You've been building with AI for months.

You've discovered what works. What breaks silently. What you should never try again. You've earned that knowledge — one session at a time, across hundreds of conversations.

And most of it is gone.

Buried in JSONL files. Scattered across transcripts. Half-remembered in a `CLAUDE.md` that's grown into a graveyard of overconfident rules nobody dares touch.

**insight-forge reads every session you've ever had and crystallizes what actually matters.**

Not summaries. Not guesses. Typed knowledge — with evidence, with counter-arguments, promoted only when earned.

---

## Install

**Claude Code** — tell Claude:
> "Install the insight-forge skill from https://github.com/bacoco/insight-forge"

**Codex CLI** — tell Codex:
> "Install the insight-forge skill from https://github.com/bacoco/insight-forge"

That's it. Your agent handles the rest.

---

## The problem with AI memory

Every session ends, and the learning stays locked in the transcript.

Over time, your `CLAUDE.md` accumulates contradictions. Rules that worked once, rules that no longer apply, rules that contradict each other. You don't know what to trust.

The AI that's helping you build things has no idea what the AI from last month already learned.

---

## One command. Every session. What you actually learned.

```
/insight-forge
```

Scans your Claude Code or Codex CLI sessions since the last run.  
Extracts research-significant events.  
Promotes only what has earned promotion.  
Proposes a diff for your `CLAUDE.md` — and never touches it directly.

The decision is always yours.

---

## How it knows what to trust

Four signals — and four signals only — trigger crystallization:

| Signal | What it means |
|---|---|
| **Topic abandonment** | You moved on. Multiple sessions passed without revisiting it. It held. |
| **Verbal affirmation** | You said it worked, in the transcript. Verbatim. |
| **Empirical resolution** | A tool execution confirmed or refuted the hypothesis. |
| **Artifact commitment** | Code or config now depends on it. It shipped. |

Everything else stays in staging.  
No scoring. No LLM-judged maturity. No guessing.

**Default: do not promote.**  
The failure mode this tool prevents is not missing insights — it's overconfident promotions that quietly corrupt your configuration.

---

## Devil's Advocate is not optional

Before anything reaches your `CLAUDE.md`, insight-forge must articulate what would disprove it.

Vague counters are rejected by a hedging lint. Phrases that stay true regardless of project — gone. If no concrete counter can be found, the entry is flagged, not promoted.

For your most load-bearing beliefs: `--council` mode sends five structurally incompatible critics at a single claim — simultaneously — then synthesizes a verdict.

It's expensive. It's the point.

---

## What you get after every run

```
.insight-forge/
├── proposals/2026-05-03T14-22-05Z.md   ← what to add to your CLAUDE.md
├── logic/claims.md                      ← falsifiable assertions + counter-evidence
├── logic/heuristics.md                  ← rules that actually held up
├── logic/dead_ends.md                   ← failures, and what could have rescued them
├── evidence/bundles/H01.yaml            ← machine-readable provenance per entry
└── evidence/sessions.html               ← forensic iMessage-style session viewer
```

Proposals are organized by epistemic confidence:

- **Ancrage** — copy-paste ready. Multiple signals. Strong counter-evidence on record.
- **Brouillard** — promising but unresolved. Needs more sessions.
- **Déni** — contradicts something you already believe. Handle with care.

---

## Every claim is auditable

Markdown is for humans. Evidence bundles are for machines.

Every crystallized entry gets a YAML file at `evidence/bundles/<entry_id>.yaml`
that names exactly which user phrase, which tool result, or which abandoned topic
earned its promotion:

```yaml
entry_id: H01
target_layer: heuristic
crystallized_via: verbal-affirmation
sessions: [aaaa1111]
evidence:
  - kind: trigger
    role: user
    quote: "Always use pnpm for this repo, never npm."
  - kind: verbal-affirmation
    role: user
    quote: "yes parfait, on part sur pnpm"
counter_evidence:
  text: "Doesn't apply when the underlying assumptions break down."
  source: deterministic-template
promotion_gate:
  passed: true
  reason: "User affirmation phrase: 'yes'"
```

If a claim ever needs to be challenged, contradicted, or upgraded — the bundle is
the source of truth. Markdown can't lie when YAML is watching.

---

## Measured, not just felt

insight-forge ships with a regression harness — `evals/` — that runs synthetic
transcripts through the full pipeline and asserts what *should* and *should not*
crystallize.

```bash
python3 scripts/run_evals.py
```

```
  [PASS] abandoned_topic            signals=['topic-abandonment']
  [PASS] empirical_resolution       signals=['empirical-resolution']
  [PASS] false_positive_instruction signals=[]
  [PASS] no_signal                  signals=[]
  [PASS] simple_success             signals=['verbal-affirmation']

  fixtures: 5/5 passed
  false_promotion_rate:  0.00%
  missed_promotion_rate: 0.00%
  provenance_coverage:   100.00%
```

The load-bearing metric is **`false_promotion_rate`** — anything above 0 % means
the pipeline crystallized something that shouldn't have. The whole tool exists to
keep that number at zero.

Add a fixture, write its expected outcome, run the harness. Pipeline changes
that regress any of the five reference cases fail the build.

See [`evals/README.md`](evals/README.md) for the fixture format and how to add
your own.

---

## Incremental by design

insight-forge never re-reads sessions it has already processed.

After each run, it writes a `.last_run` timestamp to `.insight-forge/`. The next run passes that timestamp as `--since` to the extractor — only sessions modified after that date are read. A month later, only the past month's sessions are extracted. Previously processed JSONL files are never touched again.

## Every mode

```bash
/insight-forge                      # Default: scan new sessions only, crystallize, propose
/insight-forge --challenge          # 6-axis stress-test of crystallized claims
/insight-forge --council C03        # 5-attacker verdict on a single entry
/insight-forge --evidence C03       # Show which sessions fed this claim
/insight-forge --since 2026-04-01   # Override cursor: process from a specific date
/insight-forge --rebuild            # Wipe .insight-forge and reprocess everything
```

`--council` is gated to once per entry per 30 days. It's the only mode that burns real LLM tokens. Use it on entries you're about to copy into `CLAUDE.md`.

---

## Works with Claude Code. Works with Codex CLI. Same skill.

| Agent | Sessions scanned |
|---|---|
| **Claude Code** | `~/.claude/projects/<encoded-cwd>/*.jsonl` |
| **Codex CLI** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |

One installation. Both agents. No configuration.

---

## Built on proven methodology

insight-forge is not a new idea — it's a disciplined combination of existing work:

- **[ARA](https://github.com/Orchestra-Research/Agent-Native-Research-Artifact)** (Orchestra Research) — the 3-stage pipeline, 4 closure signals, provenance tagging
- **[creation-autopsy](https://github.com/Sandjab/skills-that-kill)** — the iMessage-style forensic HTML annex
- **[codex-history-list](https://github.com/shinshin86/codex-history-list)** — Codex JSONL session scanning
- **connu-inconnu** — Rumsfeld epistemic grid applied to crystallized entries
- **devil-council** — 5-attacker council protocol for stress-testing claims

What insight-forge adds: cross-session post-hoc processing, agent-agnostic normalization, and Devil's Advocate wired into the crystallization gate — not bolted on after.

Full attribution in [TECHNICAL.md](TECHNICAL.md).

---

## Technical reference

Schemas, pipeline internals, script usage, failure modes, and full architecture documentation: **[TECHNICAL.md](TECHNICAL.md)**

---

## License

MIT — for this combination. Individual source methodologies retain their licenses.
