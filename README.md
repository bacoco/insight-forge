# Insight Forge

![Insight Forge](assets/banner.jpg)

### Your AI sessions know more than you think.

---

You've been building with AI for months.

You've discovered what works. What breaks silently. What you should never try again. You've earned that knowledge — one session at a time, across hundreds of conversations.

And most of it is gone.

Buried in JSONL files. Scattered across transcripts. Half-remembered in a `CLAUDE.md` that's grown into a graveyard of overconfident rules nobody dares touch.

**insight-forge reads every session you've ever had and tells you what you actually learned.**

Not summaries. Not guesses. Project rules and dead ends — quoted from your own words, dated, with the moment you confirmed each one.

---

## Install

**Claude Code** — tell Claude:
> "Install the insight-forge skill from https://github.com/bacoco/insight-forge"

**Codex CLI** — tell Codex:
> "Install the insight-forge skill from https://github.com/bacoco/insight-forge"

That's it. Your agent handles the rest.

---

## What you'll see

Run it once. You'll get a friendly summary in your terminal:

```
  Insight Forge — proposal for CLAUDE.md
  ────────────────────────────────────────────────────────
  ✓ 3 project rules ready
      • Use pnpm not npm
      • Always run lint:fix before committing
      • Tests live in tests/, not __tests__/
  ✗ 1 dead end to avoid
      • Don't use the npm run validate script
  · 5 observations still in staging (need more sessions)

  Full proposal — open or paste from:
    .insight-forge/proposals/2026-05-05T12-28-15Z.md
```

Open the proposal and every suggestion shows you why it's there:

```markdown
### Heuristics (project rules)

- **H01**: Use pnpm not npm
  - *You said* (May 1): "Always use pnpm for this repo, never npm."
  - *You confirmed* (May 1): "yes parfait, on part sur pnpm"
  - *Sessions*: [aaaa1111]
```

Nothing is invented. Every line cites the moment in your transcripts where you actually earned it.

---

## How it decides what to keep

Four signals — and four signals only — earn a place in your proposal:

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

Vague counters are rejected. Phrases that stay true regardless of project — gone. If no concrete counter can be found, the entry is flagged, not promoted.

For your most load-bearing beliefs: `--council` mode sends five structurally incompatible critics at a single claim — simultaneously — then synthesizes a verdict.

It's expensive. It's the point.

---

## What lands on disk after each run

```
.insight-forge/
├── proposals/2026-05-03T14-22-05Z.md   ← what to add to your CLAUDE.md
├── logic/heuristics.md                  ← rules that actually held up
├── logic/claims.md                      ← falsifiable assertions
├── logic/dead_ends.md                   ← failures, and what could have rescued them
└── evidence/                            ← which words earned each promotion
```

Proposals are organized by epistemic confidence:

- **Ancrage** — copy-paste ready. Multiple signals. Strong counter-evidence on record.
- **Brouillard** — promising but unresolved. Needs more sessions.
- **Déni** — contradicts something you already believe. Handle with care.

---

## Why you can trust it

- **Every suggestion cites your transcripts.** Each rule shows the exact phrase you used and the moment you confirmed it. If a claim is ever challenged, the receipts are right there.
- **Conservative by default.** No promotion without one of the four signals above. When in doubt, the answer is *stay in staging*.
- **Regression-tested.** A suite of synthetic transcripts asserts what should and shouldn't crystallize. Pipeline changes that would let an over-confident rule slip through fail the build.
- **Never auto-edits anything.** insight-forge writes to `.insight-forge/proposals/`. Your `CLAUDE.md` only changes when you decide to copy something into it.

How it's built — pipeline, classifier rules, eval harness, contributor guide:
[`TECHNICAL.md`](TECHNICAL.md), [`harness/README.md`](harness/README.md), [`evals/README.md`](evals/README.md).

---

## Incremental by design

insight-forge never re-reads sessions it has already processed.

After each run, it writes a `.last_run` timestamp to `.insight-forge/`. The next run passes that timestamp to the extractor — only sessions modified after that date are read. A month later, only the past month's sessions are extracted. Previously processed JSONL files are never touched again.

---

## Every mode

```bash
/insight-forge                      # Default: scan new sessions, propose
/insight-forge --challenge          # 6-axis stress-test of crystallized claims
/insight-forge --council C03        # 5-attacker verdict on a single entry
/insight-forge --evidence C03       # Show which sessions fed this claim
/insight-forge --since 2026-04-01   # Process from a specific date
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

## The research it draws on

Two recent academic papers shaped how the project stays trustworthy as it grows. The implementations aren't decorative — they ship in the codebase today.

### The classifier rules live as data, not code

> *Pan et al., **Natural-Language Agent Harnesses**, Tsinghua University, 2026.*
> arXiv: [2603.25723](https://arxiv.org/abs/2603.25723)

The paper argues that an agent's control logic should live as a portable, editable artifact — not buried in Python regex inside a controller script.

**What this means in insight-forge.** The classifier rules — *what counts as a heuristic, what counts as a constraint, what counts as a falsifiable claim* — live in [`harness/rules.yaml`](harness/rules.yaml). You can edit a regex, add a phrase, tighten a length threshold, all without touching code. Each rule names which test fixtures it must (or must not) fire on, so a careless edit fails immediately with a contract violation. And every promotion writes a `evidence/bundles/<id>.yaml` file naming the exact transcript moment that earned it — readable by humans, queryable by tools.

### A safe loop that improves the rules over time

> *Lee et al., **Meta-Harness: End-to-End Optimization of Model Harnesses**, Stanford University, 2026.*
> arXiv: [2603.28052](https://arxiv.org/abs/2603.28052)

The paper shows that once a harness is data with measurable contracts, an automated proposer can edit it and grade itself by how the eval metrics move.

**What this means in insight-forge.** When you find a real session where a rule should have fired but didn't, you mark the case as a *known gap* in the test fixtures. Then run [`scripts/propose_rules.py`](scripts/propose_rules.py) — it generates candidate edits, sandboxes each in a temporary copy of `rules.yaml`, runs the full test suite against it, and only surfaces edits that close the gap **without breaking any existing case**. The result lands in `harness/proposals/` for you to review. The proposer never edits `rules.yaml` directly — same conservative contract as the `CLAUDE.md` proposal flow.

The current proposer is deterministic (no LLM cost, fully reproducible). The mutation generator is the single swappable seam — an LLM-based generator drops in without touching the sandboxing or scoring code.

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

## References

Academic papers that directly shape the implementation:

- Pan, L., Zou, L., Guo, S., Ni, J., Zheng, H.-T. (2026). *Natural-Language Agent Harnesses*. Tsinghua University. [arXiv:2603.25723](https://arxiv.org/abs/2603.25723)
- Lee, Y., Nair, R., Zhang, Q., Lee, K., Khattab, O., Finn, C. (2026). *Meta-Harness: End-to-End Optimization of Model Harnesses*. Stanford University. [arXiv:2603.28052](https://arxiv.org/abs/2603.28052)

Methodology and source projects (full attribution in [TECHNICAL.md](TECHNICAL.md)):

- ARA — [Orchestra-Research/Agent-Native-Research-Artifact](https://github.com/Orchestra-Research/Agent-Native-Research-Artifact)
- creation-autopsy — [Sandjab/skills-that-kill](https://github.com/Sandjab/skills-that-kill)
- codex-history-list — [shinshin86/codex-history-list](https://github.com/shinshin86/codex-history-list)

---

## License

MIT — for this combination. Individual source methodologies retain their licenses.
