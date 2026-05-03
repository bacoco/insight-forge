#!/usr/bin/env python3
"""
Insight Forge — ARA pipeline core.

Reads the normalized event stream produced by extract_claude.py / extract_codex.py
and updates the .insight-forge/ knowledge base via the 3-stage pipeline:

  Stage 1 — Context Harvester  (extract candidate events)
  Stage 2 — Event Router       (classify, route direct or staged)
  Stage 3 — Maturity Tracker   (crystallize on closure signals)

USAGE:
    python3 pipeline.py --input <normalized.jsonl> [--forge-dir .insight-forge]
                        [--challenge] [--rebuild]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ============================================================
# YAML lite (so we don't depend on PyYAML)
# ============================================================
# We write YAML manually with a small set of conventions; we read it via a
# minimalist parser that handles only the structures we generate.

def yaml_dump_simple(data: dict, indent: int = 0) -> str:
    """Dump a dict to YAML. Handles only nested dicts, lists, strings, ints, bools, None."""
    lines = []
    pad = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                if not v:
                    lines.append(f"{pad}{k}: {{}}")
                else:
                    lines.append(f"{pad}{k}:")
                    lines.append(yaml_dump_simple(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{pad}{k}: []")
                else:
                    lines.append(f"{pad}{k}:")
                    for item in v:
                        if isinstance(item, dict):
                            # First key inline with -, rest indented at pad+4 spaces
                            keys = list(item.keys())
                            first_k = keys[0]
                            first_v = item[first_k]
                            if isinstance(first_v, (dict, list)):
                                # Edge: first value is a container — emit on its own line
                                lines.append(f"{pad}  -")
                                if isinstance(first_v, list):
                                    if not first_v:
                                        lines.append(f"{pad}    {first_k}: []")
                                    else:
                                        lines.append(f"{pad}    {first_k}:")
                                        for x in first_v:
                                            lines.append(f"{pad}      - {_yaml_scalar(x)}")
                                else:  # dict
                                    if not first_v:
                                        lines.append(f"{pad}    {first_k}: {{}}")
                                    else:
                                        lines.append(f"{pad}    {first_k}:")
                                        lines.append(yaml_dump_simple(first_v, indent + 3))
                            else:
                                lines.append(f"{pad}  - {first_k}: {_yaml_scalar(first_v)}")
                            for k2 in keys[1:]:
                                v2 = item[k2]
                                if isinstance(v2, list):
                                    if not v2:
                                        lines.append(f"{pad}    {k2}: []")
                                    else:
                                        lines.append(f"{pad}    {k2}:")
                                        for x in v2:
                                            if isinstance(x, dict):
                                                # nested dict in list — rare but possible
                                                lines.append(yaml_dump_simple({"_": [x]}, indent + 2)
                                                             .replace("_:\n", "", 1))
                                            else:
                                                lines.append(f"{pad}      - {_yaml_scalar(x)}")
                                elif isinstance(v2, dict):
                                    if not v2:
                                        lines.append(f"{pad}    {k2}: {{}}")
                                    else:
                                        lines.append(f"{pad}    {k2}:")
                                        lines.append(yaml_dump_simple(v2, indent + 3))
                                else:
                                    lines.append(f"{pad}    {k2}: {_yaml_scalar(v2)}")
                        else:
                            lines.append(f"{pad}  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    return "\n".join(lines)


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    s = str(v)
    # Quote if the string contains special chars
    if any(c in s for c in [":", "#", "\n", "  ", "[", "]", "{", "}", "&", "*", "?"]) or s != s.strip():
        # Multi-line: use folded quoted
        if "\n" in s:
            indented = s.replace("\n", "\\n")
            return f'"{indented}"'
        return f'"{s.replace(chr(34), chr(92) + chr(34))}"'
    if s == "" or s.lower() in ("null", "true", "false", "yes", "no"):
        return f'"{s}"'
    return s


def yaml_load_simple(text: str) -> dict:
    """Very minimal YAML loader. Handles top-level lists and nested dicts.
    Falls back to JSON if PyYAML is unavailable.
    """
    # Try a JSON-ish fallback first
    try:
        # If somebody saved as JSON
        return json.loads(text)
    except Exception:
        pass

    # Manual parser for our specific schema
    result = {}
    lines = text.split("\n")
    stack = [(0, result)]  # (indent, container)

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        # List item
        if stripped.startswith("- "):
            # Find parent key
            while stack and stack[-1][0] > indent:
                stack.pop()
            container = stack[-1][1] if stack else result
            # Parse the rest as a key:value
            rest = stripped[2:]
            if ":" in rest:
                k, _, v = rest.partition(":")
                k, v = k.strip(), v.strip()
                item = {k: _parse_scalar(v)}
                if isinstance(container, list):
                    container.append(item)
                # Look ahead for indented sibling keys of this list item
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    nxt_strip = nxt.strip()
                    if not nxt_strip or nxt_strip.startswith("#"):
                        j += 1
                        continue
                    if nxt_indent <= indent + 2 and nxt_strip.startswith("- "):
                        break
                    if nxt_indent < indent + 2:
                        break
                    if ":" in nxt_strip:
                        k2, _, v2 = nxt_strip.partition(":")
                        item[k2.strip()] = _parse_scalar(v2.strip())
                    j += 1
                i = j
                continue
            i += 1
            continue

        # Key:value or key:
        if ":" in stripped:
            k, _, v = stripped.partition(":")
            k, v = k.strip(), v.strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else result
            if v == "" or v == "[]":
                # Look at next non-blank line to decide list vs dict
                if v == "[]":
                    parent[k] = []
                else:
                    # Peek
                    j = i + 1
                    next_line = ""
                    while j < len(lines):
                        candidate = lines[j].strip()
                        if candidate and not candidate.startswith("#"):
                            next_line = lines[j]
                            break
                        j += 1
                    if next_line.strip().startswith("-"):
                        parent[k] = []
                        stack.append((indent, parent[k]))
                    else:
                        parent[k] = {}
                        stack.append((indent, parent[k]))
            else:
                parent[k] = _parse_scalar(v)
        i += 1

    return result


def _parse_scalar(v: str):
    if v == "null" or v == "" or v == "~":
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace("\\n", "\n")
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x.strip()) for x in inner.split(",")]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


# ============================================================
# Forge state I/O
# ============================================================

class ForgeState:
    """Wrapper around .insight-forge/ — read/write files."""

    def __init__(self, forge_dir: Path):
        self.dir = forge_dir
        self._init_dirs()

    def _init_dirs(self):
        for sub in ["logic", "trace", "staging", "evidence", "proposals", ".cache"]:
            (self.dir / sub).mkdir(parents=True, exist_ok=True)

    def init_if_missing(self, project_name: str = ""):
        """Seed empty files if they don't exist."""
        seeds = {
            "INSIGHTS.md": f"# Insight Forge — {project_name or 'project'}\n\nStructured knowledge base distilled from prior sessions.\n\n- `logic/` — crystallized typed knowledge\n- `trace/` — journey facts and DAG\n- `staging/` — observations awaiting closure signal\n- `evidence/` — rendered session annexes\n- `proposals/` — pending CLAUDE.md / AGENTS.md updates\n",
            "trace/session_index.yaml": "sessions: []\n",
            "trace/exploration_tree.yaml": "tree: []\n",
            "trace/pipeline_log.yaml": "runs: []\n",
            "staging/observations.yaml": "observations: []\n",
            "logic/claims.md": "# Claims\n",
            "logic/heuristics.md": "# Heuristics\n",
            "logic/dead_ends.md": "# Dead Ends\n",
            "logic/concepts.md": "# Concepts\n",
            "logic/constraints.md": "# Constraints\n",
            "evidence/README.md": "# Evidence\n\nRendered session transcripts (iMessage-style HTML) live here.\n",
            "proposals/README.md": "# Proposals\n\nPending updates to `CLAUDE.md` / `AGENTS.md` for user review.\n",
        }
        for rel, content in seeds.items():
            p = self.dir / rel
            if not p.exists():
                p.write_text(content, encoding="utf-8")
        last_run = self.dir / ".last_run"
        if not last_run.exists():
            last_run.write_text("", encoding="utf-8")

    def read_yaml(self, rel: str) -> dict:
        p = self.dir / rel
        if not p.exists():
            return {}
        return yaml_load_simple(p.read_text(encoding="utf-8"))

    def write_yaml(self, rel: str, data: dict):
        p = self.dir / rel
        p.write_text(yaml_dump_simple(data) + "\n", encoding="utf-8")

    def append_md(self, rel: str, content: str):
        p = self.dir / rel
        with p.open("a", encoding="utf-8") as f:
            f.write("\n" + content + "\n")

    def read_md(self, rel: str) -> str:
        p = self.dir / rel
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def get_last_run(self) -> Optional[str]:
        p = self.dir / ".last_run"
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8").strip()
        return text or None

    def set_last_run(self, ts: str, last_session_id: str = ""):
        p = self.dir / ".last_run"
        p.write_text(f"{ts}\nlast_session: {last_session_id}\n", encoding="utf-8")

    def next_id(self, layer: str) -> str:
        """Allocate the next ID for a given layer (N, O, C, H, D, K, R)."""
        prefix_map = {
            "tree": "N",
            "observation": "O",
            "claim": "C",
            "heuristic": "H",
            "dead_end": "D",
            "concept": "K",
            "constraint": "R",
        }
        prefix = prefix_map.get(layer, "X")

        max_id = 0
        # Scan all relevant files
        files_to_scan = [
            self.dir / "logic" / "claims.md",
            self.dir / "logic" / "heuristics.md",
            self.dir / "logic" / "dead_ends.md",
            self.dir / "logic" / "concepts.md",
            self.dir / "trace" / "exploration_tree.yaml",
            self.dir / "staging" / "observations.yaml",
        ]
        pattern = re.compile(rf"\b{prefix}(\d+)\b")
        for f in files_to_scan:
            if f.exists():
                for m in pattern.finditer(f.read_text(encoding="utf-8")):
                    max_id = max(max_id, int(m.group(1)))

        return f"{prefix}{max_id + 1:02d}"


# ============================================================
# Stage 1 — Context Harvester
# ============================================================

@dataclass
class CandidateEvent:
    """Output of the harvester, input to the router."""
    session_id: str
    session_short: str
    agent: str
    timestamp: str
    role: str
    content: str
    tool_name: Optional[str] = None
    tool_status: Optional[str] = None
    cwd: str = ""
    # Context window (surrounding messages)
    prev_role: str = ""
    prev_content: str = ""
    next_role: str = ""
    next_content: str = ""


def harvest(normalized_path: Path) -> tuple[list[CandidateEvent], list[dict]]:
    """Read normalized.jsonl, group by session, emit candidate events.
    Returns (candidates, session_metadatas)."""
    candidates = []
    session_metas = []
    current_meta = None
    buffer = []

    def flush_session():
        if not buffer:
            return
        # Walk buffer, emit each event with prev/next context
        for i, ev in enumerate(buffer):
            prev = buffer[i - 1] if i > 0 else {}
            nxt = buffer[i + 1] if i + 1 < len(buffer) else {}
            candidates.append(CandidateEvent(
                session_id=ev.get("session_id", ""),
                session_short=ev.get("session_short", ""),
                agent=ev.get("agent", ""),
                timestamp=ev.get("timestamp", ""),
                role=ev.get("role", ""),
                content=ev.get("content", ""),
                tool_name=ev.get("tool_name"),
                tool_status=ev.get("tool_status"),
                cwd=ev.get("cwd", ""),
                prev_role=prev.get("role", ""),
                prev_content=prev.get("content", ""),
                next_role=nxt.get("role", ""),
                next_content=nxt.get("content", ""),
            ))

    with normalized_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            marker = obj.get("_marker")
            if marker == "session_start":
                current_meta = {k: v for k, v in obj.items() if k != "_marker"}
                buffer = []
                session_metas.append(current_meta)
            elif marker == "session_end":
                flush_session()
                buffer = []
            else:
                buffer.append(obj)

        # Final flush in case last session has no end marker
        if buffer:
            flush_session()

    return candidates, session_metas


# ============================================================
# Stage 2 — Event Router
# ============================================================

# Affirmation triggers (FR + EN, case-insensitive, accent-folded)
AFFIRMATION_PHRASES = [
    "yes", "oui", "confirmed", "confirme", "correct", "exact", "c'est ça", "cest ca",
    "let's go with", "on part sur", "ship it", "exactly", "precisement", "right",
    "go for it", "vas-y", "vas y", "perfect", "parfait", "good", "bien",
]

REJECT_PHRASES = [
    "no, rather", "non plutot", "non, plutot", "pas comme ça", "pas comme ca",
    "non, x au lieu de y", "actually let's", "wait, instead", "no, instead",
    "non, au lieu", "pas du tout", "wrong", "faux",
]

DEAD_END_PHRASES = [
    "scratch that", "nope, that doesn't work", "ne marche pas", "ça ne fonctionne pas",
    "let's revert", "annule ça", "annule ca", "rollback", "abandonne", "give up on",
    "not gonna work", "doesn't work",
]

PIVOT_PHRASES = [
    "actually let's switch", "wait, different approach", "on change d'approche",
    "pivot to", "let me try a different way", "scrap this",
]

# Assistant messages that are work-progress narration, not durable knowledge.
# Matched case-insensitively against the start of the content.
META_WORK_PREFIXES = re.compile(
    r"^(i'?m |i am )(checking|reviewing|looking|reading|scanning|analyzing|verifying|"
    r"running|fixing|updating|writing|creating|finding|searching|examining|inspecting)\b"
    r"|^(i'?ve |i have )(reviewed|checked|looked|found|read|scanned|run|updated|written|"
    r"created|analyzed|verified|confirmed|identified|examined|inspected)\b"
    r"|^(let me |let's )(check|look|read|review|scan|run|verify|create|write|update|fix|"
    r"examine|inspect|analyze|search|find)\b"
    r"|^(checking|reading|looking|scanning|reviewing|analyzing|verifying|running|examining)\b"
    r"|^(the |this )(repo|repository|branch|file|directory|codebase|code) (is |has |contains |shows )"
    r"|^repo is (on|at|tracking)\b"
    r"|^(branch|tracking|local changes|working directory)\b",
    re.IGNORECASE,
)


def normalize_text(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.lower()).strip()


def _truncate_at_word(s: str, max_len: int) -> str:
    """Truncate at the nearest word boundary, with ellipsis if truncated."""
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    # Find the last space before max_len
    cut = s.rfind(" ", 0, max_len)
    if cut == -1 or cut < max_len // 2:
        cut = max_len  # word too long, hard cut
    return s[:cut].rstrip(",.!?;:") + "…"


def contains_any(text: str, phrases: list[str]) -> Optional[str]:
    """Return the first phrase found in text (normalized), or None."""
    nt = normalize_text(text)
    for p in phrases:
        if normalize_text(p) in nt:
            return p
    return None


@dataclass
class RoutedEvent:
    """Output of the router, input to the maturity tracker (or directly written)."""
    candidate: CandidateEvent
    route: str  # 'direct' or 'staged' or 'skip'
    type_: str  # node type or potential_type
    provenance: str  # user / ai-suggested / ai-executed / user-revised
    confidence: str  # high / medium / low
    distilled: str  # cleaned content for the entry
    extra: dict = field(default_factory=dict)  # type-specific fields


def classify_and_route(ev: CandidateEvent) -> Optional[RoutedEvent]:
    """Apply the decision tree from event-taxonomy.md."""

    content = ev.content or ""
    content_norm = normalize_text(content)

    # === Hard skips ===
    if not content.strip():
        return None
    if len(content_norm) < 3:
        return None
    if ev.role in ("system",):
        return None

    # === Detect dead_end ===
    if ev.role == "user":
        phrase = contains_any(content, DEAD_END_PHRASES)
        if phrase:
            return RoutedEvent(
                candidate=ev,
                route="direct",
                type_="dead_end",
                provenance="user",
                confidence="high",
                distilled=content[:300],
                extra={
                    "hypothesis": ev.prev_content[:300] if ev.prev_role == "assistant" else "",
                    "failure_mode": "explicitly abandoned",
                    "lesson": content[:200],
                    "could_have_worked_if": "not_explored",
                    "trigger_phrase": phrase,
                },
            )

    # Tool error → potential dead_end if not recovered next
    if ev.role == "tool_result" and ev.tool_status == "error":
        return RoutedEvent(
            candidate=ev,
            route="staged",
            type_="dead_end",
            provenance="ai-executed",
            confidence="medium",
            distilled=f"Tool failed: {ev.tool_name or '?'}",
            extra={
                "failure_mode": content[:300],
                "could_have_worked_if": "not_explored",
            },
        )

    # === Detect pivot ===
    if ev.role == "user":
        phrase = contains_any(content, PIVOT_PHRASES)
        if phrase:
            return RoutedEvent(
                candidate=ev,
                route="direct",
                type_="pivot",
                provenance="user",
                confidence="high",
                distilled=content[:300],
                extra={
                    "from_": ev.prev_content[:200] if ev.prev_role == "assistant" else "",
                    "to": "",  # to be filled by next event
                    "trigger": phrase,
                },
            )

    # === Detect heuristic FIRST (always/never patterns trump decision regex) ===
    if ev.role == "user" and re.match(r"^\s*(always|never|toujours|jamais|don'?t|ne pas|prefer|avoid)\b",
                                       content, re.IGNORECASE):
        return RoutedEvent(
            candidate=ev,
            route="staged",
            type_="heuristic",
            provenance="user",
            confidence="high",
            distilled=content[:300],
            extra={},
        )

    # === Detect explicit decision ===
    if ev.role == "user":
        # Patterns like "let's go with X" / "use Y instead of Z"
        m = re.search(r"(let'?s go with|on part sur|use|utilise|prefer)\s+([A-Za-z0-9_-]+)",
                      content, re.IGNORECASE)
        if m:
            return RoutedEvent(
                candidate=ev,
                route="direct",
                type_="decision",
                provenance="user",
                confidence="high",
                distilled=content[:300],
                extra={
                    "choice": m.group(2),
                    "alternatives": [],
                    "evidence": [],
                },
            )

    # === Detect successful tool_use as ai-executed action ===
    if ev.role == "tool_use" and ev.tool_name in {"Edit", "Write", "MultiEdit", "apply_patch", "edit_file", "write_file"}:
        return RoutedEvent(
            candidate=ev,
            route="direct",
            type_="experiment",
            provenance="ai-executed",
            confidence="medium",
            distilled=f"Code change via {ev.tool_name}",
            extra={
                "hypothesis": ev.prev_content[:300] if ev.prev_role in ("user", "assistant") else "",
                "result": "pending",
            },
        )

    # === Detect questions ===
    if ev.role == "user" and "?" in content[-5:]:
        # User question that was not immediately answered
        next_is_clarification = ev.next_role == "assistant" and "?" in ev.next_content[:100]
        if next_is_clarification:
            return RoutedEvent(
                candidate=ev,
                route="direct",
                type_="question",
                provenance="user",
                confidence="medium",
                distilled=content[:300],
                extra={"description": content[:500], "status": "open"},
            )

    # === Stage potentially interpretive content ===
    # Falsifiable claim from assistant
    if ev.role == "assistant":
        # Skip progress-narration messages — they are activity traces, not durable knowledge.
        if META_WORK_PREFIXES.match(content.strip()):
            return None
        # "X is faster than Y" / "Z always fails"
        if re.search(r"\b(is|are|works|fails|always|never)\b.*\b(than|on|when|because)\b",
                      content, re.IGNORECASE) and len(content) < 400:
            return RoutedEvent(
                candidate=ev,
                route="staged",
                type_="claim",
                provenance="ai-suggested",
                confidence="low",
                distilled=content[:300],
                extra={},
            )

    # Constraint
    if re.search(r"\b(must|requires|requires? at least|doit|nécessite|requires)\s+\S+",
                 content, re.IGNORECASE) and ev.role == "user":
        return RoutedEvent(
            candidate=ev,
            route="staged",
            type_="constraint",
            provenance="user",
            confidence="medium",
            distilled=content[:300],
            extra={},
        )

    # No classification — drop
    return None


# ============================================================
# Stage 3 — Maturity Tracker
# ============================================================

@dataclass
class CrystallizationDecision:
    observation_id: str
    fired_signal: Optional[str]  # 'topic-abandonment' | 'verbal-affirmation' | 'empirical-resolution' | 'artifact-commitment' | None
    target_layer: Optional[str]  # 'claim' | 'heuristic' | 'dead_end' | 'concept' | 'constraint' | None
    reason: str
    counter_evidence: str  # generated counter-clause


def detect_verbal_affirmation(observation: dict, candidates: list[CandidateEvent]) -> Optional[str]:
    """Look for first-person user affirmation within ~3 turns of the observation."""
    obs_session = observation.get("session_id", "")[:8]
    obs_ts = observation.get("timestamp", "")

    # Collect candidates from same session, after observation
    later = [c for c in candidates
             if c.session_short == obs_session and c.timestamp > obs_ts and c.role == "user"]
    later.sort(key=lambda c: c.timestamp)

    # Take the next ~3 user turns
    for c in later[:3]:
        phrase = contains_any(c.content, AFFIRMATION_PHRASES)
        if phrase and not contains_any(c.content, ["maybe", "probably", "peut-etre", "sans doute"]):
            return phrase

    return None


def detect_topic_abandonment(observation: dict, all_sessions: list[dict],
                              k: int = 5) -> bool:
    """Topic absent from last k sessions and no open_threads reference."""
    obs_session = observation.get("session_id", "")[:8]
    obs_content = observation.get("content", "")

    # Take noun-phrase keywords from observation
    keywords = [w.lower() for w in re.findall(r"\b[A-Za-z]{5,}\b", obs_content)][:5]
    if not keywords:
        return False

    # Get the k most recent sessions, excluding the observation's own session
    sorted_sessions = sorted(all_sessions, key=lambda s: s.get("date", ""))
    recent = [s for s in sorted_sessions if s.get("id", "") != obs_session][-k:]

    if len(recent) < k:
        return False  # Not enough sessions to call abandonment

    # Check summary fields for keywords
    for s in recent:
        summary = (s.get("summary", "") or "").lower()
        if any(kw in summary for kw in keywords):
            return False  # Topic was revisited

    return True


def detect_empirical_resolution(observation: dict, candidates: list[CandidateEvent]) -> Optional[str]:
    """Check if a tool result resolved the observation.
    Requires keyword overlap between observation content and tool result — without
    this, any subsequent tool error would falsely 'refute' unrelated observations.
    """
    obs_session = observation.get("session_id", "")[:8]
    obs_ts = observation.get("timestamp", "")
    obs_content = observation.get("content", "")

    # Extract content keywords (≥4 chars, lowercased, accent-folded, dedupe)
    obs_keywords = {normalize_text(w) for w in re.findall(r"\b[A-Za-z][A-Za-z0-9_]{3,}\b", obs_content)}
    if not obs_keywords:
        return None

    later_results = [c for c in candidates
                     if c.session_short == obs_session
                     and c.timestamp > obs_ts
                     and c.role == "tool_result"]

    # Require overlap: at least one keyword from the observation must appear in the result
    for c in later_results[:5]:
        result_text = normalize_text(c.content)
        overlap = any(kw in result_text for kw in obs_keywords if len(kw) >= 4)
        if not overlap:
            continue
        if c.tool_status == "ok":
            return "supported"
        if c.tool_status == "error":
            return "refuted"
    return None


def generate_counter_evidence(observation: dict, type_: str) -> str:
    """Generate a counter-evidence clause for Devil's Advocate.
    In a real deployment this would call an LLM; here we use a template-based fallback.
    """
    content = observation.get("content", "")[:200]
    if type_ == "claim":
        return f"Would be refuted by an observation showing the opposite of: {content[:120]}"
    if type_ == "heuristic":
        return f"Doesn't apply when the underlying assumptions of '{content[:80]}' break down"
    if type_ == "dead_end":
        return f"Could have worked if the missing precondition for '{content[:80]}' had been met"
    return "not_explored"


def evaluate_maturity(obs: dict, all_candidates: list[CandidateEvent],
                       all_sessions: list[dict]) -> CrystallizationDecision:
    """Apply the 4 closure signals."""
    obs_id = obs.get("id", "?")
    pot_type = obs.get("potential_type", "unknown")

    # Already promoted?
    if obs.get("promoted"):
        return CrystallizationDecision(obs_id, None, None, "already promoted", "")

    # Map potential_type to target_layer
    target_map = {
        "claim": "claim",
        "heuristic": "heuristic",
        "dead_end": "dead_end",
        "concept": "concept",
        "constraint": "constraint",
        "architecture": "claim",  # treat as claim
        "unknown": None,
    }
    target = target_map.get(pot_type)
    if target is None:
        return CrystallizationDecision(obs_id, None, None, "unknown type, defer", "")

    # Signal 2: verbal affirmation
    affirmation = detect_verbal_affirmation(obs, all_candidates)
    if affirmation:
        return CrystallizationDecision(
            obs_id, "verbal-affirmation", target,
            f"User affirmation phrase: '{affirmation}'",
            generate_counter_evidence(obs, target),
        )

    # Signal 3: empirical resolution
    resolution = detect_empirical_resolution(obs, all_candidates)
    if resolution == "supported":
        return CrystallizationDecision(
            obs_id, "empirical-resolution", target,
            "Tool result confirmed observation",
            generate_counter_evidence(obs, target),
        )
    if resolution == "refuted":
        # Promote to dead_end instead
        return CrystallizationDecision(
            obs_id, "empirical-resolution", "dead_end",
            "Tool result refuted observation — promoted to dead_end",
            generate_counter_evidence({"content": obs.get("content", "")}, "dead_end"),
        )

    # Signal 1: topic abandonment
    if detect_topic_abandonment(obs, all_sessions):
        return CrystallizationDecision(
            obs_id, "topic-abandonment", target,
            "Topic absent from recent sessions",
            generate_counter_evidence(obs, target),
        )

    # Signal 4: artifact commitment
    # (Hard to check without actual git/file scanning — left as TODO)

    # No signal fired
    return CrystallizationDecision(obs_id, None, None, "no signal fired", "")


# ============================================================
# Writers — turn typed data into ARA files
# ============================================================

def write_dead_end(state: ForgeState, did: str, fields: dict):
    md = f"""
## {did}: {fields.get('title', 'untitled')}
- **Hypothesis tested**: {fields.get('hypothesis', '?')}
- **Failure mode**: {fields.get('failure_mode', '?')}
- **Lesson**: {fields.get('lesson', '?')}
- **Could have worked if**: {fields.get('could_have_worked_if', 'not_explored')}
- **Provenance**: {fields.get('provenance', 'unknown')}
- **Code refs**: {fields.get('code_refs', '[pending]')}
- **Sessions**: [{', '.join(fields.get('sessions', []))}]
- **Avoid signal**: {fields.get('avoid_signal', '[pending]')}
"""
    state.append_md("logic/dead_ends.md", md.strip())


def write_claim(state: ForgeState, cid: str, fields: dict):
    md = f"""
## {cid}: {fields.get('title', 'untitled')}
- **Statement**: {fields.get('statement', '?')}
- **Status**: {fields.get('status', 'hypothesis')}
- **Provenance**: {fields.get('provenance', 'unknown')}
- **Crystallized via**: {fields.get('crystallized_via', '?')}
- **Counter-evidence**: {fields.get('counter_evidence', 'not_explored')}
- **Falsification criteria**: {fields.get('falsification', '[pending]')}
- **Proof**: {fields.get('proof', '[pending]')}
- **Dependencies**: {fields.get('dependencies', '[]')}
- **Tags**: {fields.get('tags', '')}
- **From staging**: {fields.get('from_staging', '?')}
- **Sessions**: [{', '.join(fields.get('sessions', []))}]
"""
    state.append_md("logic/claims.md", md.strip())


def write_heuristic(state: ForgeState, hid: str, fields: dict):
    md = f"""
## {hid}: {fields.get('title', 'untitled')}
- **Rule**: {fields.get('rule', '?')}
- **Rationale**: {fields.get('rationale', '?')}
- **Provenance**: {fields.get('provenance', 'unknown')}
- **Crystallized via**: {fields.get('crystallized_via', '?')}
- **Sensitivity**: {fields.get('sensitivity', 'medium')}
- **Code refs**: {fields.get('code_refs', '[pending]')}
- **Counter-cases**: {fields.get('counter_cases', 'not_explored')}
- **From staging**: {fields.get('from_staging', '?')}
- **Sessions**: [{', '.join(fields.get('sessions', []))}]
"""
    state.append_md("logic/heuristics.md", md.strip())


def write_concept(state: ForgeState, kid: str, fields: dict):
    md = f"""
## {kid}: {fields.get('title', 'untitled')}
- **Definition**: {fields.get('definition', '?')}
- **Status**: {fields.get('status', 'active')}
- **Provenance**: {fields.get('provenance', 'unknown')}
- **Crystallized via**: {fields.get('crystallized_via', '?')}
- **Counter-evidence**: {fields.get('counter_evidence', 'not_explored')}
- **From staging**: {fields.get('from_staging', '?')}
- **Sessions**: [{', '.join(fields.get('sessions', []))}]
"""
    state.append_md("logic/concepts.md", md.strip())


def write_constraint(state: ForgeState, rid: str, fields: dict):
    md = f"""
## {rid}: {fields.get('title', 'untitled')}
- **Rule**: {fields.get('rule', '?')}
- **Scope**: {fields.get('scope', 'project-wide')}
- **Provenance**: {fields.get('provenance', 'unknown')}
- **Crystallized via**: {fields.get('crystallized_via', '?')}
- **Counter-evidence**: {fields.get('counter_evidence', 'not_explored')}
- **From staging**: {fields.get('from_staging', '?')}
- **Sessions**: [{', '.join(fields.get('sessions', []))}]
"""
    state.append_md("logic/constraints.md", md.strip())


def append_tree_node(state: ForgeState, node: dict):
    tree_data = state.read_yaml("trace/exploration_tree.yaml")
    if "tree" not in tree_data:
        tree_data["tree"] = []
    tree_data["tree"].append(node)
    state.write_yaml("trace/exploration_tree.yaml", tree_data)


def append_observation(state: ForgeState, obs: dict):
    obs_data = state.read_yaml("staging/observations.yaml")
    if "observations" not in obs_data:
        obs_data["observations"] = []
    obs_data["observations"].append(obs)
    state.write_yaml("staging/observations.yaml", obs_data)


def update_observation(state: ForgeState, obs_id: str, updates: dict):
    obs_data = state.read_yaml("staging/observations.yaml")
    for o in obs_data.get("observations", []):
        if o.get("id") == obs_id:
            o.update(updates)
            break
    state.write_yaml("staging/observations.yaml", obs_data)


# ============================================================
# Main pipeline
# ============================================================

def run_pipeline(input_path: Path, forge_dir: Path,
                 challenge: bool = False, rebuild: bool = False) -> dict:
    """Execute the full pipeline. Returns a summary dict."""

    if rebuild and forge_dir.exists():
        # Confirmation handled by caller; here we just wipe non-config files
        for sub in ["logic", "trace", "staging"]:
            for f in (forge_dir / sub).glob("*"):
                if f.is_file():
                    f.unlink()
        last_run = forge_dir / ".last_run"
        if last_run.exists():
            last_run.unlink()

    state = ForgeState(forge_dir)
    state.init_if_missing(project_name=forge_dir.parent.name)

    # === Stage 1 ===
    candidates, session_metas = harvest(input_path)
    print(f"[insight-forge] Stage 1 — Harvested {len(candidates)} candidates from {len(session_metas)} session(s)",
          file=sys.stderr)

    # === Stage 2 ===
    direct_count = 0
    staged_count = 0
    routed: list[RoutedEvent] = []
    for cand in candidates:
        decision = classify_and_route(cand)
        if decision is None:
            continue
        routed.append(decision)
        if decision.route == "direct":
            direct_count += 1
            # Write directly to exploration_tree
            nid = state.next_id("tree")
            node = {
                "id": nid,
                "type": decision.type_,
                "title": _truncate_at_word(decision.distilled, 60),
                "provenance": decision.provenance,
                "timestamp": cand.timestamp,
                "session_id": cand.session_short,
                "status": "open",
            }
            node.update(decision.extra)
            append_tree_node(state, node)
        elif decision.route == "staged":
            staged_count += 1
            oid = state.next_id("observation")
            obs = {
                "id": oid,
                "timestamp": cand.timestamp,
                "provenance": decision.provenance,
                "content": decision.distilled,
                "context": cand.prev_content[:200],
                "potential_type": decision.type_,
                "bound_to": [],
                "promoted": False,
                "promoted_to": None,
                "crystallized_via": None,
                "stale": False,
                "last_referenced": cand.timestamp[:10],
                "session_id": cand.session_short,
                "confidence": decision.confidence,
            }
            append_observation(state, obs)

    print(f"[insight-forge] Stage 2 — {direct_count} direct, {staged_count} staged",
          file=sys.stderr)

    # === Stage 3 — Maturity Tracker ===
    obs_data = state.read_yaml("staging/observations.yaml")
    crystallized_count = 0
    contradictions = 0

    for obs in obs_data.get("observations", []):
        if obs.get("promoted"):
            continue
        # Build a session_index-like list for topic-abandonment check
        all_session_summaries = [{"id": m.get("session_short", ""), "date": m.get("mtime", ""),
                                  "summary": ""} for m in session_metas]
        decision = evaluate_maturity(obs, candidates, all_session_summaries)

        if decision.fired_signal is None:
            # Stale check
            try:
                last_ref = datetime.fromisoformat(obs.get("last_referenced", "")[:10])
                age = datetime.now(tz=timezone.utc).replace(tzinfo=None) - last_ref
                if age > timedelta(days=14) and not obs.get("stale"):
                    update_observation(state, obs.get("id", ""), {"stale": True})
            except Exception:
                pass
            continue

        # Crystallize
        crystallized_count += 1
        target = decision.target_layer
        new_id = state.next_id(target)

        # Provenance upgrade rule: verbal-affirmation upgrades ai-suggested → user-revised
        original_provenance = obs.get("provenance", "unknown")
        upgraded_provenance = original_provenance
        if decision.fired_signal == "verbal-affirmation" and original_provenance == "ai-suggested":
            upgraded_provenance = "user-revised"

        common_fields = {
            "title": _truncate_at_word(obs.get("content", ""), 60),
            "provenance": upgraded_provenance,
            "crystallized_via": decision.fired_signal,
            "from_staging": obs.get("id", ""),
            "sessions": [obs.get("session_id", "")],
            "counter_evidence": decision.counter_evidence,
        }

        if target == "dead_end":
            common_fields.update({
                "hypothesis": obs.get("context", "")[:200],
                "failure_mode": obs.get("content", "")[:200],
                "lesson": obs.get("content", "")[:200],
                "could_have_worked_if": decision.counter_evidence,
                "code_refs": "[pending]",
                "avoid_signal": obs.get("content", "")[:80],
            })
            write_dead_end(state, new_id, common_fields)
        elif target == "claim":
            common_fields.update({
                "statement": obs.get("content", "")[:300],
                "status": "supported" if decision.fired_signal == "empirical-resolution" else "hypothesis",
                "falsification": "[pending]",
                "proof": "[pending]",
                "dependencies": "[]",
                "tags": "",
            })
            write_claim(state, new_id, common_fields)
        elif target == "heuristic":
            common_fields.update({
                "rule": obs.get("content", "")[:200],
                "rationale": obs.get("context", "")[:200] or "[pending]",
                "sensitivity": "medium",
                "code_refs": "[pending]",
                "counter_cases": decision.counter_evidence,
            })
            write_heuristic(state, new_id, common_fields)
        elif target == "concept":
            common_fields.update({
                "definition": obs.get("content", "")[:300],
                "status": "active",
            })
            write_concept(state, new_id, common_fields)
        elif target == "constraint":
            common_fields.update({
                "rule": obs.get("content", "")[:300],
                "scope": "project-wide",
            })
            write_constraint(state, new_id, common_fields)
        else:
            # Unknown target — do NOT mark as promoted; leave in staging.
            print(f"[insight-forge] Warning: no writer for target '{target}' "
                  f"(obs {obs.get('id', '?')}) — left in staging", file=sys.stderr)
            crystallized_count -= 1
            continue

        # Mark observation as promoted
        update_observation(state, obs.get("id", ""), {
            "promoted": True,
            "promoted_to": f"logic/{target}s.md:{new_id}",
            "crystallized_via": decision.fired_signal,
        })

    print(f"[insight-forge] Stage 3 — {crystallized_count} crystallized",
          file=sys.stderr)

    # === Update session_index ===
    idx_data = state.read_yaml("trace/session_index.yaml")
    if "sessions" not in idx_data:
        idx_data["sessions"] = []
    existing_ids = {s.get("id") for s in idx_data["sessions"]}
    for meta in session_metas:
        sid = meta.get("session_short", "")
        if sid in existing_ids:
            continue
        # Count events for this session
        evs_in_session = [c for c in candidates if c.session_short == sid]
        idx_data["sessions"].append({
            "id": sid,
            "full_id": meta.get("session_id", ""),
            "agent": meta.get("agent", ""),
            "date": meta.get("mtime", "")[:10],
            "cwd": "",
            "turn_count": 0,
            "file_size_kb": meta.get("size_kb", 0),
            "summary": "",
            "events_extracted": len(evs_in_session),
            "observations_staged": 0,
            "crystallizations": 0,
            "contradictions_flagged": 0,
        })
    state.write_yaml("trace/session_index.yaml", idx_data)

    # === Update pipeline_log ===
    log_data = state.read_yaml("trace/pipeline_log.yaml")
    if "runs" not in log_data:
        log_data["runs"] = []
    log_data["runs"].append({
        "run_id": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sessions_processed": [m.get("session_short", "") for m in session_metas],
        "candidates": len(candidates),
        "direct": direct_count,
        "staged": staged_count,
        "crystallized": crystallized_count,
        "contradictions": contradictions,
    })
    state.write_yaml("trace/pipeline_log.yaml", log_data)

    # === Update last_run ===
    last_session = session_metas[-1].get("session_id", "") if session_metas else ""
    state.set_last_run(datetime.now(timezone.utc).isoformat(timespec="seconds"), last_session)

    summary = {
        "candidates": len(candidates),
        "sessions": len(session_metas),
        "direct": direct_count,
        "staged": staged_count,
        "crystallized": crystallized_count,
        "contradictions": contradictions,
    }
    return summary


def main():
    p = argparse.ArgumentParser(description="Run the insight-forge ARA pipeline.")
    p.add_argument("--input", type=str, required=True,
                   help="Path to normalized.jsonl produced by extract_*.py")
    p.add_argument("--forge-dir", type=str, default=".insight-forge",
                   help="Path to .insight-forge/ directory.")
    p.add_argument("--challenge", action="store_true",
                   help="Run Devil's Advocate sweep over crystallized claims.")
    p.add_argument("--rebuild", action="store_true",
                   help="Discard existing .insight-forge/ and reprocess from scratch.")
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[insight-forge] Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    forge_dir = Path(args.forge_dir)
    summary = run_pipeline(input_path, forge_dir, args.challenge, args.rebuild)

    print(f"[insight-forge] Done. {summary}", file=sys.stderr)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
