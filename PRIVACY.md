# Privacy

## Where data lives

`insight-forge` is a **local-first** tool. It reads transcripts that already
exist on your machine, writes structured knowledge into a per-project
`.insight-forge/` directory, and proposes (never auto-applies) diffs to
`CLAUDE.md` / `AGENTS.md`. **No transcript leaves your machine** in the
default flow.

| File | Where it lives | What it contains |
|---|---|---|
| Claude Code sessions | `~/.claude/projects/<encoded-cwd>/*.jsonl` | Full transcripts you've recorded with Claude Code |
| Codex CLI sessions | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | Full transcripts you've recorded with Codex CLI |
| Knowledge base | `<project>/.insight-forge/` | Crystallized rules, claims, dead ends, evidence bundles |
| Proposals | `<project>/.insight-forge/proposals/<ts>.md` | Drafts for `CLAUDE.md` / `AGENTS.md` (you decide what to apply) |

## What goes over the network

By default: **nothing**. The default invocation (`/insight-forge`) makes
zero network calls — it reads JSONL files, runs deterministic regex/text
matching, writes Markdown and YAML.

Two opt-in modes do call an LLM:

- **`--council`** — sends a single crystallized entry to five attacker
  prompts (your configured LLM). Gated to once per entry per 30 days.
- **`--challenge`** — sends crystallized claims through a 6-axis
  stress-test prompt. Same opt-in semantics.

Neither mode is invoked unless you explicitly pass the flag, and the body
of each request is exactly the entry being challenged plus the protocol
prompt — never the full transcript.

## What's in the evidence bundles

Every crystallized entry has an evidence bundle at
`.insight-forge/evidence/bundles/<entry_id>.yaml` that **stores verbatim
quotes from your transcripts**. This is the trade-off the tool makes:
verifiable provenance requires storing the exact text that earned each
promotion.

The bundles can therefore contain anything you typed into your AI
assistant — including code snippets, configuration values, command lines
with arguments, error messages, and (depending on what you discussed)
potentially sensitive material.

## Recommendations

1. **Gitignore `.insight-forge/`** in any repository where the surrounding
   project is public. The default `.gitignore` shipped with this repo
   already does this for the project itself.

2. **Review proposals before applying.** The proposal Markdown also
   contains your verbatim quotes. The friendly summary on stderr does
   not — it shows only rule titles.

3. **Use `--redact` if you're sharing a proposal.** Before sharing
   `.insight-forge/proposals/<ts>.md` (e.g. as part of a bug report),
   run with `--redact` to replace likely secrets (AWS keys, GitHub
   tokens, JWTs, email addresses, etc.) with `<REDACTED:type>` markers.
   See `scripts/redact.py` for the pattern list.

4. **Treat `--council` and `--challenge` like any LLM call.** The body
   of these requests goes to your configured LLM provider under their
   privacy terms.

## What the project will never do

- Auto-apply a proposal to `CLAUDE.md` / `AGENTS.md`. The human is the
  only authority that modifies those files.
- Send a transcript to any service without an explicit `--council` /
  `--challenge` invocation.
- Phone home for telemetry.
- Add a remote logging or analytics integration.

## Reporting a privacy concern

See [`SECURITY.md`](SECURITY.md).
