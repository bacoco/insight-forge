# Council Protocol

Adapted from the **devil-council** skill (see README for credits). The native `--challenge` mode of insight-forge searches for refuting evidence using the same signal that promoted the claim — tautological. The council mode replaces it with 5 structurally incompatible methods of attack.

## When to invoke

Council is **expensive** (5 LLM calls + 1 synthesis). Reserve it for:

- High-stakes claims about to be copied into `CLAUDE.md` / `AGENTS.md`
- Entries the quadrant mapping (`known-unknown-mapping.md`) flags as `Déni`
- Cristallized claims older than 90 days about to drive new architectural decisions
- Any entry the user has explicitly tagged as load-bearing

Do NOT invoke council on:

- Staged observations (let them mature first)
- Simple decisions that resolved cleanly via tool execution (already `Ancrage`)
- Trivial entries with low downstream impact
- Bulk knowledge bases (run `--challenge` instead — no LLM cost)

## Architecture

The Python preparator does not call any LLM. It writes 6 prompt files and a manifest into `.insight-forge/council/<entry_id>-<date>/`. The agent (Claude Code or Codex CLI) orchestrates execution through its native sub-agent system.

```
preparator (council.py)
   ↓ writes
.insight-forge/council/C03-2026-05-03/
   ├── 00-target.md             ← target framing + extracted context
   ├── 01-falsificationniste.prompt.md
   ├── 02-pre-mortem.prompt.md
   ├── 03-inverseur.prompt.md
   ├── 04-contraintes-first.prompt.md
   ├── 05-second-ordre.prompt.md
   ├── 06-procureur.prompt.md   ← template, completed by agent after attacks
   └── README.md                ← orchestration instructions
   ↓
agent reads README, spawns 5 sub-agents in parallel
   ↓
agent collects 5 responses, completes 06-procureur.prompt.md, runs synthesis
   ↓
final output written to:
.insight-forge/council/C03-2026-05-03/
   ├── attack-01-falsificationniste.md   ← LLM response 1
   ├── attack-02-pre-mortem.md
   ├── attack-03-inverseur.md
   ├── attack-04-contraintes-first.md
   ├── attack-05-second-ordre.md
   └── verdict.md                        ← Procureur synthesis
```

## The 5 attackers

Verbatim adaptation from devil-council. These are not personas — they are **irrevocable reasoning constraints**.

### 1. Le Falsificationniste
**Method**: Karl Popper. A proposition has value only if refutable — and the Falsificationist must try to refute.
**Irrevocable rule**: NOT ALLOWED to confirm anything. Mission: find the fatal counter-example, the data that invalidates the thesis, the experiment that would prove it false.
**Output**: A decisive test. "If condition X holds, the claim collapses. Here is how to verify."

### 2. Le Pré-mortem
**Method**: Gary Klein. Project into a future where the decision was made and failed spectacularly. Work backward to identify why.
**Irrevocable rule**: Failure is CERTAIN. Not probable, not possible — certain. No success scenario.
**Output**: The autopsy of a not-yet-occurred disaster.

### 3. L'Inverseur
**Method**: Systematic inversion. If consensus says A, defend non-A with rigor.
**Irrevocable rule**: MUST argue the exact opposite of the claim. Not contrarianism — methodological discipline.
**Output**: A rigorous antithesis.

### 4. Le Contraintes-First
**Method**: Constraints reasoning. Ignore benefits, opportunities, potential. See only what's missing.
**Irrevocable rule**: NOT ALLOWED to mention benefits. See only limits: budget, time, skills, dependencies, missing prerequisites, technical and organizational debt.
**Output**: A criticality-ranked inventory of gaps.

### 5. Le Second-Ordre
**Method**: Systems thinking. Ignore direct effects (everyone sees them). See only 2nd and 3rd order consequences, cascade effects, feedback loops.
**Irrevocable rule**: NOT ALLOWED to discuss direct effects. Only: "and then?", "and that triggers what?", "and who reacts how?".
**Output**: A cascade map.

## Why these 5

They form three structural tensions that prevent convergence:

- **Falsificationniste vs Inverseur**: the first hunts the factual flaw within the claim; the second argues the entire claim is inverted
- **Pré-mortem vs Second-Ordre**: the first looks at one specific failed future; the second looks at unforeseen systemic cascades
- **Contraintes-First** anchors the other four in concrete reality, preventing pure abstraction

If a claim survives 5 incompatible methods, it has earned a real counter_evidence clause. If not, the verdict tells the user where exactly it broke.

## The Procureur (synthesis)

After collecting all 5 attacks, the agent runs a 6th call: the Procureur. This is NOT a peer review of the attackers — it's a synthesis with these 5 sections:

1. **Convergence des attaques** — points where multiple incompatible methods independently arrive at the same weakness. Strongest signal.
2. **Divergences méthodologiques** — where methods contradict. Don't smooth out — explain why rigorous methods reach opposite conclusions.
3. **Angles morts collectifs** — what the 5 methods missed *together*. The critical question: what angle did NONE cover? What assumptions did all attackers share without questioning?
4. **Diagnostic** — clear verdict. The claim resists or it doesn't. No "it depends".
5. **Le point de rupture** — THE single most dangerous flaw. The one that, if unaddressed, makes the rest irrelevant.

## Output: updating the entry

The verdict.md output is read by the user. The user decides what to do:

- If verdict says claim resists → update `counter_evidence` field with the specific surviving counter-clauses identified
- If verdict identifies a rupture point → user can choose to:
  - Downgrade the claim's `status` to `weakened`
  - Add a `superseded_by` field pointing to a new claim that incorporates the rupture
  - Move to staged with a `was_council_attacked: true` flag
- If verdict identifies blind spots → these become new staged observations for future cycles

The pipeline does NOT auto-modify the entry. The council is decision support, not decision enforcement.

## Cost discipline

Council mode burns ~6× the tokens of a simple `--challenge`. To keep this honest:

- Hard limit: **one council per entry per 30 days** unless `--force` is passed
- Council results stored permanently — do not re-run if a verdict already exists for the same entry
- The `--council all` syntax is intentionally absent — the user must specify a single entry ID
- Suggested workflow: run `--challenge` first (cheap), see what it surfaces, then `--council` only the most concerning entries

## Anti-patterns

- **Council to confirm a claim**: don't invoke council to feel good about a claim. Invoke it because you suspect a flaw and want it surfaced. Confirmation bias dressed as rigor is worse than no rigor.
- **Council on stale claims as a ritual**: 90-day claims are eligible but only if they're still load-bearing. Don't council old claims that nobody is using anymore.
- **Modifying the attacker prompts to be "fair"**: the constraints are deliberately one-sided. Each attacker is a lens. "Fair" attackers converge — that's exactly what we're avoiding.
