#!/usr/bin/env python3
"""
Insight Forge — council preparator (5 attackers + procureur).

Does NOT call any LLM. Reads a cristallized entry from .insight-forge/logic/,
extracts its evidence and context, then writes 6 prompt files into
.insight-forge/council/<id>-<date>/. The agent (Claude Code or Codex CLI)
orchestrates execution via its native sub-agent / Task tool.

USAGE:
    python3 council.py --entry C03 [--forge-dir .insight-forge] [--force]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ============================================================
# Entry lookup
# ============================================================

ID_TO_FILE = {
    "C": "logic/claims.md",
    "H": "logic/heuristics.md",
    "D": "logic/dead_ends.md",
    "K": "logic/concepts.md",
}


def parse_md_entry(text: str, entry_id: str) -> dict:
    """Pull a single ## block by ID. Returns dict of fields."""
    pattern = rf"^## {re.escape(entry_id)}:.*?(?=^## [A-Z]\d+:|\Z)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return {}
    block = m.group(0)
    lines = block.split("\n")
    title = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
    fields = {"id": entry_id, "title": title, "_raw_block": block}
    for line in lines[1:]:
        m2 = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*:\s*(.*)$", line)
        if m2:
            fields[m2.group(1).strip()] = m2.group(2).strip()
    return fields


def find_entry(forge_dir: Path, entry_id: str) -> tuple[dict, str]:
    """Locate entry across logic files. Returns (entry_dict, source_file)."""
    prefix = entry_id[0]
    rel = ID_TO_FILE.get(prefix)
    if not rel:
        return {}, ""
    p = forge_dir / rel
    if not p.exists():
        return {}, ""
    text = p.read_text(encoding="utf-8")
    entry = parse_md_entry(text, entry_id)
    return entry, str(p)


def collect_session_excerpts(forge_dir: Path, session_ids: list[str],
                              max_lines: int = 50) -> str:
    """Pull representative lines from normalized.jsonl for the given sessions."""
    cache = forge_dir / ".cache" / "normalized.jsonl"
    if not cache.exists():
        return "(no cached normalized.jsonl — run extract_*.py first)"

    excerpts = []
    in_target_session = False
    current_session = ""
    line_count = 0

    with cache.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            marker = obj.get("_marker")
            if marker == "session_start":
                sid = obj.get("session_short", "")[:8]
                in_target_session = sid in session_ids
                current_session = sid
                if in_target_session:
                    excerpts.append(f"\n--- session {sid} ---")
                continue
            if marker == "session_end":
                in_target_session = False
                continue
            if in_target_session and line_count < max_lines:
                role = obj.get("role", "")
                content = obj.get("content", "")[:300]
                excerpts.append(f"[{role}] {content}")
                line_count += 1

    if not excerpts:
        return "(no session excerpts found for the referenced session IDs)"
    return "\n".join(excerpts)


def parse_session_ids(entry: dict) -> list[str]:
    """Extract session ID list from the 'Sessions' field."""
    sessions = entry.get("Sessions", "[]")
    return [x.strip() for x in re.findall(r"[a-f0-9]{4,}", sessions)]


# ============================================================
# Prompt templates
# ============================================================

ATTACKER_TEMPLATE = """# Attacker: {name}

## Your reasoning constraint (irrevocable)

{constraint}

**ABSOLUTE RULE**: {rule}

## The target

{target}

## Your task

Attack this target from your constraint. Do not nuance. Do not seek balance. Your method is your only weapon — use it fully. The other 4 attackers cover the angles you don't cover.

Output 150-300 words in {language}. No preamble. Attack directly.
"""

PROCUREUR_TEMPLATE = """# Procureur — Council Synthesis

You are the Procureur of the Insight Forge Council. Your task: synthesize the 5 attacks into a final verdict.

## The target

{target}

## The 5 attacks

### Falsificationniste
{attack_1}

### Pré-mortem
{attack_2}

### Inverseur
{attack_3}

### Contraintes-First
{attack_4}

### Second-Ordre
{attack_5}

## Your task

Produce the council verdict with this exact structure:

## Convergence des attaques
[Points where multiple methods independently converge = confirmed weaknesses]

## Divergences méthodologiques
[Where methods contradict and why — this is information, not noise]

## Angles morts collectifs
[CRITICAL: what did the 5 methods miss together? What assumptions did all attackers share without questioning? What angle did NO constraint cover?]

## Diagnostic
[Clear verdict. The claim resists or not. No "it depends".]

## Le point de rupture
[ONE single flaw. The most dangerous. The one that makes the rest irrelevant if unaddressed.]

Be direct. Do not nuance. The Council exists to surface the truth nobody wants to hear. Respond in {language}.
"""

ATTACKER_DEFS = [
    {
        "id": "01-falsificationniste",
        "name": "Le Falsificationniste",
        "constraint": "Karl Popper's falsificationism. A proposition has value only if refutable — and you must try to refute it.",
        "rule": "You are NOT ALLOWED to confirm anything. Your only mission is to find the fatal counter-example, the data that would invalidate this claim, the experiment that would prove it false. If you find nothing after exhausting all paths, you may admit it — but only after exhausting them.",
    },
    {
        "id": "02-pre-mortem",
        "name": "Le Pré-mortem",
        "constraint": "Gary Klein's pre-mortem. Project into a future where the decision based on this claim was made and failed spectacularly. Work backward to identify why.",
        "rule": "Failure is CERTAIN. Not probable, not possible — certain. You are NOT ALLOWED to consider any success scenario. You must write the autopsy of a disaster that has not yet occurred.",
    },
    {
        "id": "03-inverseur",
        "name": "L'Inverseur",
        "constraint": "Systematic inversion. If the claim says A, you defend non-A with rigor and conviction.",
        "rule": "You MUST argue the exact opposite of what this claim asserts. Not contrarianism for its own sake — methodological discipline. If the claim is 'X is faster than Y', you defend 'Y is faster than X' with full rigor.",
    },
    {
        "id": "04-contraintes-first",
        "name": "Le Contraintes-First",
        "constraint": "Constraints-first reasoning. Ignore all benefits, opportunities, and potential. See only what is missing.",
        "rule": "You are NOT ALLOWED to discuss benefits. You see only limits: budget, time, skills, dependencies, missing resources, unmet prerequisites, technical debt, organizational debt. If a critical resource is missing, name it. If a prerequisite is unmet, name it.",
    },
    {
        "id": "05-second-ordre",
        "name": "Le Second-Ordre",
        "constraint": "Systems thinking. Ignore direct effects (everyone sees them). Consider only 2nd and 3rd order consequences, cascade effects, feedback loops.",
        "rule": "You are NOT ALLOWED to discuss the direct effects of acting on this claim. Only: 'and then?', 'and that triggers what?', 'and who reacts how?'. The systemic effects, the perverse incentives, the unintended consequences.",
    },
]


# ============================================================
# Target framing
# ============================================================

def frame_target(entry: dict, source_file: str, excerpts: str) -> str:
    """Build the target description that all attackers see."""
    eid = entry.get("id", "?")
    title = entry.get("title", "(no title)")
    
    body_parts = [
        f"# Target for council attack: {eid}",
        f"",
        f"## The crystallized entry",
        f"",
        f"**ID**: {eid}",
        f"**Source**: `{source_file}`",
        f"**Title**: {title}",
        f"",
    ]
    
    important_fields = [
        "Statement", "Rule", "Hypothesis tested", "Failure mode", "Lesson",
        "Status", "Provenance", "Crystallized via",
        "Counter-evidence", "Counter-cases", "Could have worked if",
        "Falsification criteria", "Proof", "Code refs",
        "Sensitivity", "Sessions",
    ]
    
    for k in important_fields:
        if k in entry:
            body_parts.append(f"**{k}**: {entry[k]}")
    
    body_parts.extend([
        "",
        "## Implicit assumptions to question",
        "",
        "The claim above was crystallized from one or more sessions. The crystallization signal that promoted it (see 'Crystallized via' field) does NOT mean the claim is true — it means a closure heuristic fired. Your task is to attack the substance of the claim itself, regardless of how it was promoted.",
        "",
        "## What's at stake",
        "",
        f"This entry sits in the project's knowledge base. If it's wrong, downstream decisions inherit the error. If it gets copied into CLAUDE.md / AGENTS.md, the agent will operate on it as if true across all future sessions. The cost of being wrong is high.",
        "",
        "## Session excerpts that fed this entry",
        "",
        "```",
        excerpts,
        "```",
        "",
    ])
    
    return "\n".join(body_parts)


# ============================================================
# Output writers
# ============================================================

def write_attacker_prompt(out_dir: Path, attacker: dict, target: str, language: str = "français"):
    prompt = ATTACKER_TEMPLATE.format(
        name=attacker["name"],
        constraint=attacker["constraint"],
        rule=attacker["rule"],
        target=target,
        language=language,
    )
    p = out_dir / f"{attacker['id']}.prompt.md"
    p.write_text(prompt, encoding="utf-8")


def write_procureur_prompt(out_dir: Path, target: str, language: str = "français"):
    """Write the procureur prompt template — the agent will fill in attacks before calling LLM."""
    placeholder = "[insert sub-agent response here]"
    prompt = PROCUREUR_TEMPLATE.format(
        target=target,
        attack_1=placeholder, attack_2=placeholder, attack_3=placeholder,
        attack_4=placeholder, attack_5=placeholder,
        language=language,
    )
    p = out_dir / "06-procureur.prompt.md"
    p.write_text(prompt, encoding="utf-8")


def write_orchestration_readme(out_dir: Path, entry: dict):
    """Instructions for the agent (Claude Code / Codex CLI) on how to run the council."""
    eid = entry.get("id", "?")
    content = f"""# Council session for {eid}

## What this is

5 attacker prompts + 1 procureur prompt have been prepared. Your task is to:

1. Spawn 5 sub-agents IN PARALLEL, one per attacker prompt
2. Collect their responses
3. Substitute the responses into `06-procureur.prompt.md`
4. Run the procureur as a 6th call
5. Save the verdict to `verdict.md`

## How to orchestrate (Claude Code)

Use the `Task` tool to spawn 5 sub-agents in parallel. Pass each one the contents of the matching `0X-*.prompt.md` file as the prompt. Wait for all 5. Then:

```
Read 01-*.prompt.md → Task tool → save response to attack-01-falsificationniste.md
Read 02-*.prompt.md → Task tool → save response to attack-02-pre-mortem.md
... (in parallel)
```

Then read all 5 attack files, substitute into 06-procureur.prompt.md (replace `[insert sub-agent response here]` placeholders), and run a 6th Task call. Save to `verdict.md`.

## How to orchestrate (Codex CLI)

Use the sub-agent system (`/agent_a`, etc.). Same pattern: 5 parallel sub-agents, 1 synthesis call.

## Constraints

- Spawn the 5 attackers IN PARALLEL. Sequential execution lets earlier responses contaminate later ones.
- Pass each attacker its prompt VERBATIM. Do not edit the constraints — they are designed to be one-sided.
- The procureur sees all 5 attacks AND the original target. It does NOT do peer review of the attackers — it synthesizes their conclusions and identifies blind spots.

## After verdict

The user reads `verdict.md`. Based on the verdict, the user may:

- Update the entry's `counter_evidence` field with the surviving counter-clauses
- Downgrade `status` to `weakened` if the verdict is decisive
- Add `was_council_attacked: true` to the entry's metadata
- Move the entry to staged for re-promotion later

The pipeline NEVER auto-modifies the entry based on a council verdict. Decision support, not decision enforcement.

## Files in this directory

- `00-target.md` — the target framing all attackers see
- `01-falsificationniste.prompt.md` — Karl Popper, refutation-only
- `02-pre-mortem.prompt.md` — Gary Klein, certain failure
- `03-inverseur.prompt.md` — systematic inversion
- `04-contraintes-first.prompt.md` — only what's missing
- `05-second-ordre.prompt.md` — cascade effects only
- `06-procureur.prompt.md` — synthesis template (fill in attacks before running)
- `attack-XX-*.md` — sub-agent responses (you write these after running the prompts)
- `verdict.md` — final synthesis (you write this last)
"""
    p = out_dir / "README.md"
    p.write_text(content, encoding="utf-8")


def write_manifest(out_dir: Path, entry: dict, source_file: str):
    """Machine-readable record of the council session for future audit."""
    manifest = {
        "entry_id": entry.get("id", "?"),
        "entry_title": entry.get("title", ""),
        "source_file": source_file,
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attackers": [a["id"] for a in ATTACKER_DEFS],
        "status": "prepared",  # → "running" → "completed" by the agent
        "verdict_path": "verdict.md",
    }
    p = out_dir / "manifest.json"
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ============================================================
# Cost-discipline check
# ============================================================

def check_recent_council(forge_dir: Path, entry_id: str, force: bool) -> bool:
    """Return True if it's OK to proceed."""
    council_dir = forge_dir / "council"
    if not council_dir.exists():
        return True
    
    if force:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for sub in council_dir.iterdir():
        if not sub.is_dir():
            continue
        if not sub.name.startswith(f"{entry_id}-"):
            continue
        manifest_p = sub / "manifest.json"
        if manifest_p.exists():
            try:
                m = json.loads(manifest_p.read_text(encoding="utf-8"))
                prepared = datetime.fromisoformat(m.get("prepared_at", ""))
                if prepared.replace(tzinfo=timezone.utc) > cutoff:
                    print(f"[insight-forge] A council session for {entry_id} exists at "
                          f"{sub} (prepared {m.get('prepared_at', '?')}). "
                          f"Use --force to run another within 30 days.", file=sys.stderr)
                    return False
            except Exception:
                pass
    return True


# ============================================================
# CLI
# ============================================================

def main():
    p = argparse.ArgumentParser(description="Prepare a council session: 5 attackers + procureur prompts.")
    p.add_argument("--entry", type=str, required=True,
                   help="Entry ID to attack (e.g., C03, H07, D02)")
    p.add_argument("--forge-dir", type=str, default=".insight-forge")
    p.add_argument("--force", action="store_true",
                   help="Run even if a council session for this entry exists within 30 days.")
    p.add_argument("--language", type=str, default="français",
                   help="Output language for attackers (default: français)")
    args = p.parse_args()

    forge_dir = Path(args.forge_dir)
    if not forge_dir.exists():
        print(f"[insight-forge] Forge dir not found: {forge_dir}", file=sys.stderr)
        sys.exit(1)

    entry_id = args.entry.strip().upper()
    entry, source_file = find_entry(forge_dir, entry_id)
    if not entry:
        print(f"[insight-forge] Entry {entry_id} not found in logic/", file=sys.stderr)
        sys.exit(2)

    if not check_recent_council(forge_dir, entry_id, args.force):
        sys.exit(3)

    # Setup output directory
    today = datetime.now(timezone.utc).date().isoformat()
    out_dir = forge_dir / "council" / f"{entry_id}-{today}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build target framing
    session_ids = parse_session_ids(entry)
    excerpts = collect_session_excerpts(forge_dir, session_ids)
    target = frame_target(entry, source_file, excerpts)
    (out_dir / "00-target.md").write_text(target, encoding="utf-8")

    # Write 5 attacker prompts
    for attacker in ATTACKER_DEFS:
        write_attacker_prompt(out_dir, attacker, target, args.language)

    # Write procureur template
    write_procureur_prompt(out_dir, target, args.language)

    # Write orchestration README
    write_orchestration_readme(out_dir, entry)

    # Write manifest
    write_manifest(out_dir, entry, source_file)

    print(f"[insight-forge] Council prepared for {entry_id} at:", file=sys.stderr)
    print(f"  {out_dir}", file=sys.stderr)
    print(f"[insight-forge] Next: agent should read README.md and orchestrate "
          f"5 parallel sub-agents.", file=sys.stderr)
    print(str(out_dir))


if __name__ == "__main__":
    main()
