# Codex CLI Format Spec

Documents the structure of Codex CLI session rollout files, used by `scripts/extract_codex.py`.

## Storage path

```
$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<TIMESTAMP>-<UUID>.jsonl
```

- `CODEX_HOME` defaults to `~/.codex/`
- Files are sharded by date (NOT by project — unlike Claude Code)
- Filename: `rollout-2026-05-01T04-49-34-019ddff0-80cb-7f42-8317-8daf17d0bd7f.jsonl`
- Archived sessions move to `$CODEX_HOME/archived_sessions/`
- Index file at `$CODEX_HOME/sessions/session_index.jsonl` (append-only thread-name index)

## Implication: project filtering

Because sessions are NOT grouped by project, we must filter by `cwd`. The cwd lives in an `<environment_context>` block injected at the start of each session, **inside the first user message**. Match pattern:

```
<environment_context>
  ...
  <cwd>/Users/jp/projects/foo</cwd>
  ...
</environment_context>
```

Or potentially:

```
Working directory: /Users/jp/projects/foo
```

The exact format may evolve. The extractor should try multiple patterns and fall back to substring match on the cwd path.

## Line-level format

Each rollout file is JSONL. The first line is a `SessionMeta`; subsequent lines are `EventMsg` or `ResponseItem` (collectively `RolloutItem`).

### SessionMeta (first line)

```json
{
  "type": "session_meta",
  "session_id": "019ddff0-80cb-7f42-8317-8daf17d0bd7f",
  "timestamp": "2026-05-01T04:49:34Z",
  "model": "gpt-5.4",
  "model_provider": "openai",
  "source": "tui" | "exec" | "app-server",
  "rollout_version": 2
}
```

Schema may evolve. Tolerate unknown fields. The fields the pipeline strictly needs:
- `session_id` (full UUID — first 8 chars used as short ID)
- `timestamp`
- `model`

### EventMsg

```json
{
  "type": "event_msg",
  "msg": {
    "type": "session_configured" | "task_started" | "task_complete" | "agent_message" | "tool_call" | "tool_result" | "error" | ...,
    "session_id": "...",
    "model": "...",
    "rollout_path": "..."
  }
}
```

Most `event_msg` types are infrastructure. The pipeline only cares about a few:
- `session_configured` — confirms session start, often duplicates SessionMeta
- `task_started` / `task_complete` — turn boundaries

### ResponseItem (the meat)

```json
{
  "type": "response_item",
  "item": {
    "role": "user" | "assistant" | "system",
    "content": [...]
  }
}
```

Or for tool calls:

```json
{
  "type": "response_item",
  "item": {
    "type": "function_call",
    "name": "shell" | "apply_patch" | "read_file" | ...,
    "arguments": "{...}",
    "call_id": "..."
  }
}
```

And tool results:

```json
{
  "type": "response_item",
  "item": {
    "type": "function_call_output",
    "call_id": "...",
    "output": "...",
    "status": "completed" | "error"
  }
}
```

## Filter rules (apply BEFORE Stage 2 classification)

| Drop | Reason |
|---|---|
| `<environment_context>` blocks | System-injected, not user content |
| `<task-notification>` blocks | Internal status |
| `[Request interrupted by user]` standalone messages | Surface as pivot only if next msg explains |
| `tool_call` items where `name` ∈ {`read_file`, `list_dir`, `grep`} with no error | Pure exploration, no decision content |
| `function_call_output` longer than 100 lines | Truncate to first 30 + last 10, mark `[truncated]` |
| Hooks/system messages with `system_prompt_override` | Plumbing |
| `event_msg` types not in {`task_started`, `task_complete`} | Plumbing |
| Skill loading injections (substring `Base directory for this skill:`) | Internal |
| Empty content blocks | Noise |

## Filter rules to KEEP (despite looking like noise)

| Keep | Reason |
|---|---|
| `apply_patch` tool calls | These are decisions that touched code — high signal |
| `function_call_output` with `status: error` | Failures are valuable for dead_end detection |
| Short shell outputs (< 30 lines) | Often contain decisive evidence |
| User messages even if very short ("ok", "no") | These are closure signals |

## Project resolution

To find sessions for project `<cwd>`:

```python
import os
from pathlib import Path

def find_codex_sessions(cwd: str, codex_home: Path = None) -> list[Path]:
    codex_home = codex_home or Path.home() / ".codex"
    sessions_root = codex_home / "sessions"
    if not sessions_root.exists():
        return []

    matches = []
    for jsonl in sessions_root.rglob("rollout-*.jsonl"):
        # Read just the first ~10 lines to find the cwd
        with jsonl.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                if cwd in line:  # crude but effective
                    matches.append(jsonl)
                    break
    return matches
```

Be tolerant of:
- Trailing slashes (`/foo/bar/` vs `/foo/bar`)
- Case sensitivity on Windows
- Symlinked paths

## Edge cases

- **Empty sessions** (no real user input, just session_configured then end): record in session_index as `events_extracted: 0` and skip Stage 2.
- **Crashed sessions** (no `task_complete` event): treat as truncated. Process available content, mark `truncated: true` in session_index.
- **Resumed sessions**: Codex appends to the existing file on resume (per docs). The same session_id appears across multiple turn boundaries — that's fine, treat as continuous.
- **`experimental_resume` workflow**: same as above.
- **App-server sessions**: V2 sessions backed by the app-server use a SQLite state DB in addition to JSONL. The JSONL is still the source of truth for content. We don't read the SQLite — JSONL only.

## Cross-platform path encoding

Codex stores absolute paths verbatim in the `<environment_context>`. On Windows that means `C:\Users\jp\projects\foo`. The matcher must handle:
- Forward vs backslash (normalize before comparison)
- Drive letter case (`C:` vs `c:`)
- Extended path prefix (`\\?\C:\...`) — see Codex issue #20517 for the canonicalization bug

When matching, normalize via `Path(cwd).resolve()`.

## Sources

- [Codex CLI Reference](https://developers.openai.com/codex/cli/reference)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced)
- [Session Resumption (DeepWiki)](https://deepwiki.com/openai/codex/4.4-session-resumption-and-forking)
- Codex repo: `codex-rs/rollout/src/recorder.rs` and `codex-rs/rollout/src/session_index.rs`
- Reference impl: [codex-history-list](https://github.com/shinshin86/codex-history-list)
