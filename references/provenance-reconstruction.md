# Provenance Reconstruction (post-hoc rules)

In the original ARA `research-manager`, provenance was captured live — Claude knew, at the moment of writing, who said what. In a post-hoc skill that reads JSONL, we have to **reconstruct** provenance from the transcript. This document specifies the rules.

## The 4 provenance tags

| Tag | Meaning | Carries forward on crystallization? |
|---|---|---|
| `user` | The phrase appeared verbatim in a user message | Yes |
| `ai-suggested` | The assistant proposed it; user did not explicitly endorse | Becomes `user-revised` only on verbal affirmation |
| `ai-executed` | An assistant action successfully completed (tool_use → tool_result success) | Yes |
| `user-revised` | Pattern: assistant suggested X → user said "rather Y, not X" — the resulting Y is user-revised | Yes |

## Reconstruction rules (apply in order)

For each candidate event from the harvester:

### Rule 1 — Verbatim user content
If the candidate's `content` (the distilled fact/claim/observation) appears as a substring of a user message in the JSONL → tag `user`.

Match:
- Case-insensitive
- Whitespace-normalized
- Accent-insensitive (FR/EN ASCII fold)
- Allow up to 10% character difference (Levenshtein distance) for typos

### Rule 2 — Tool execution
If the candidate is sourced from a tool_use that produced a successful tool_result (no `error`, exit code 0 if applicable, no `interrupted` flag):
- `ai-executed` if the assistant initiated the action without a directly preceding user prompt to do that exact action
- `user-confirmed-execution` (treated as `user-revised`) if the user message immediately preceding said something like "go ahead" / "do it" / "vas-y"

### Rule 3 — Assistant suggestion, no user follow-up
If the candidate's `content` first appears in an assistant message AND no subsequent user message in the same session matches the affirmation triggers (see `crystallization-rules.md` §2) AND the user did not explicitly reject:
- Tag `ai-suggested`

### Rule 4 — Reject pattern → user-revised
Pattern detection in transcript:
```
Assistant: ... <suggestion X> ...
User: <reject phrase> + <alternative Y>
```

Reject phrases (FR/EN):
- "non, plutôt..." / "no, rather..."
- "pas comme ça, mais..."
- "non, X au lieu de Y"
- "actually let's do..."
- "wait, instead..."

When detected:
- The original X gets tagged `ai-suggested` and additionally flagged `superseded_by: O{YY}`
- The new Y gets tagged `user-revised` with `original: O{XX}` field

### Rule 5 — Default
If none of the above match, stage as `ai-suggested` and let the next run reconcile (the user might affirm in a future session).

## Special cases

### User pasting the assistant's suggestion back

If the user message contains the exact text the assistant just suggested (within 1-2 turns), that's NOT verbatim user origination — it's affirmation by repetition. Tag the underlying observation `user-revised` (the user has appropriated the wording, but it originated from the assistant).

Heuristic: if the user message is mostly assistant-generated text with minor edits, treat as affirmation, not origination.

### Subagent / Task delegation

The original ARA spec excludes subagents by default. For insight-forge:
- Subagent transcripts are scanned only if `--include-subagents` is passed
- If included, the subagent's user-role messages are NOT real user messages — they're orchestrator prompts. Tag everything in subagent transcripts as `ai-suggested` regardless of role, unless the subagent explicitly cites a user prompt from the parent session.

### Conversation compaction

Claude Code auto-compacts long sessions. The compacted summary appears as a synthetic message. **Do not extract events from compacted summaries** — they're already abstractions and would create double-counting. Skip them (filter rule).

### Codex `<environment_context>` blocks

Codex CLI injects an `<environment_context>` block at the start of each session containing cwd, git info, etc. This is system content, not user content. Filter out before classification — never extract events from it.

## Provenance upgrade table

| Initial → Trigger → New |
|---|
| `ai-suggested` → verbatim user repetition → `user-revised` |
| `ai-suggested` → user verbatim affirmation in same/next session → `user-revised` (or `user` if user used same words) |
| `ai-suggested` → user explicit rejection + alternative → original gets `superseded`, alternative gets `user-revised` |
| `ai-executed` → user comments "good" / "perfect" → upgrade to `user-revised` |
| Anything → user explicit "no, that's wrong" → flag `disputed`, do not auto-revise |

## Confidence flag (optional)

Every reconstructed provenance can carry a `confidence: high | medium | low` field:
- **high**: rule 1 (verbatim) or rule 2 (clean tool success)
- **medium**: rule 3 (no follow-up — could be silent agreement OR silent disagreement)
- **low**: rule 4 (pattern-detected revisions are noisy)

The pipeline log should record provenance decisions of `confidence: low` so the user can audit them.
