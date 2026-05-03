# Claude Code Format Spec

Documents the structure of Claude Code session JSONL files, used by `scripts/extract_claude.py`.

## Storage path

```
~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl
```

- Sessions ARE grouped by project (encoded cwd as directory name)
- Each session is a single `.jsonl` file named with its UUID
- Auto-deletion: Claude Code deletes session files after 30 days by default — surface this to the user if scanning very old projects

## CWD encoding (critical)

Claude Code encodes the project path into a directory name by replacing path separators with `-`. The exact convention differs by OS:

| OS | Original | Encoded |
|---|---|---|
| Windows | `D:\DEV\foo\bar` | `D--DEV-foo-bar` |
| POSIX | `/Users/jp/foo/bar` | `-Users-jp-foo-bar` |

Note the leading `-` on POSIX is intentional (the convention is to keep it).

## Discovery algorithm

```python
import os
from pathlib import Path

def encode_cwd(cwd: str) -> list[str]:
    """Return candidate encoded directory names for a given cwd."""
    candidates = []
    p = Path(cwd).resolve()
    s = str(p)

    if os.name == "nt":  # Windows
        # D:\DEV\foo → D--DEV-foo
        candidates.append(s.replace("\\", "-").replace(":", "-"))
        # Variant without the colon
        candidates.append(s.replace("\\", "-").replace(":", ""))
    else:
        # /Users/jp/foo → -Users-jp-foo
        candidates.append(s.replace("/", "-"))

    return candidates


def find_claude_sessions(cwd: str, claude_home: Path = None) -> list[Path]:
    claude_home = claude_home or Path.home() / ".claude"
    projects_root = claude_home / "projects"
    if not projects_root.exists():
        return []

    candidates = encode_cwd(cwd)
    for c in candidates:
        proj_dir = projects_root / c
        if proj_dir.is_dir():
            return sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return []
```

If no candidate matches, fall back to a fuzzy search: `os.listdir(projects_root)` and find the closest by Levenshtein distance to the encoded forms — propose to the user, don't auto-pick.

## Line-level format

Each line in the JSONL is a JSON object representing one event in the session timeline. The schema (as observed in real files; subject to change):

```json
{
  "uuid": "msg-uuid",
  "parent_uuid": "previous-msg-uuid",
  "session_id": "...",
  "timestamp": "ISO8601",
  "type": "user" | "assistant" | "summary" | "tool_use" | "tool_result",
  "message": {
    "role": "user" | "assistant",
    "content": [
      { "type": "text", "text": "..." },
      { "type": "tool_use", "id": "...", "name": "...", "input": {...} },
      { "type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": false }
    ]
  },
  "cwd": "...",
  "git_branch": "main",
  ...
}
```

Newer schema variants split tool_use and tool_result into top-level entries (`type: "tool_use"`, `type: "tool_result"`). The extractor must handle both.

## Filter rules (apply BEFORE Stage 2 classification)

| Drop | Reason |
|---|---|
| `<system-reminder>` blocks inside user messages | Auto-injected reminders, not user content |
| `<task-notification>` blocks | Internal status |
| `[Request interrupted by user]` standalone | Surface as pivot only if next msg explains |
| `tool_use` with name in {`Read`, `Glob`, `Grep`, `LS`} producing no error | Pure exploration, no decision content |
| `tool_result` longer than 100 lines | Truncate to first 30 + last 10 |
| Hook execution outputs (substring `Hook PreToolUse:`) | Plumbing |
| `type: "summary"` events from auto-compaction | Already an abstraction, would double-count |
| Empty content blocks | Noise |
| Skill-loading injections (substring `Base directory for this skill:`) | Internal |

## Filter rules to KEEP

| Keep | Reason |
|---|---|
| `tool_use` for `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | Code changes — high signal |
| `tool_use` for `Bash` (any command, full output if short) | Build/test commands often = experiments |
| `tool_result` with `is_error: true` | Failures = potential dead_ends |
| User messages even very short | Closure signals |
| First user message of any session | Often contains the goal |

## Project / cwd determination

The cwd field appears explicitly in most messages (top-level `cwd` field). If absent or stale (project moved), fall back to:
1. The project directory name (decoded from encoded form)
2. The first user message content if it mentions a path
3. Ask user

## Edge cases

- **Auto-compaction**: when a session crosses the context limit, Claude Code creates a synthetic `summary` message and continues. **Do not extract events from `summary` messages** — filter them.
- **Multiple sessions same day**: one project directory contains many `.jsonl` files. Sort by `mtime`. The pipeline processes in chronological order so causal relationships (claim → later refutation) are preserved.
- **Renamed projects**: old encoded-cwd directory still exists; new encoded-cwd is empty. The user must hint or run `--rebuild` after moving sessions manually.
- **Session compaction loss**: messages may be missing. The pipeline must tolerate gaps. Always check for `parent_uuid` chain breaks and log them as `truncated_at: <uuid>`.
- **Tool use IDs vs message UUIDs**: tool_use_id ties tool_result back to its tool_use. Don't confuse with message uuid.

## Subagents

Subagent invocations show up as `tool_use: Task` followed by their own response chain. Their full transcripts may or may not be in the JSONL — depends on the version. By default, the extractor:
- Records the Task invocation as a single tool_use event (input = description, output = result)
- Does NOT recurse into the subagent's transcript

Use `--include-subagents` to recurse. With that flag, treat all messages in the subagent transcript as `ai-suggested` (they're not real user messages — they're orchestrator prompts).

## Sources

- Anthropic doc on session storage (referenced indirectly via `/insights` documentation)
- Empirical observation of `~/.claude/projects/` JSONL files
- [creation-autopsy SKILL.md](../../skills-that-kill/jp/.claude/skills/creation-autopsy/SKILL.md) — its `extract_sessions.py` is the gold reference
- [claude-recap repo](https://github.com/annikalewis/claude-recap) — alternate parser
