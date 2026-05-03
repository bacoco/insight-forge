# Known-Unknown Mapping

A grid of epistemic positions, applied to the insight-forge knowledge base. Adapted from the Rumsfeld matrix and the **connu-inconnu** skill (see README for credits).

The ARA pipeline classifies entries by *type* (claim, heuristic, dead_end, concept, constraint) and *maturation status* (staged, crystallized). This document adds an **orthogonal axis**: the level of epistemic certainty.

## The 4 quadrants

```
                  KNOW IT          DON'T KNOW IT
                ┌────────────────┬───────────────────┐
   AWARE OF IT  │  ANCRAGE       │  BROUILLARD       │
                │  (known known) │  (known unknown)  │
                ├────────────────┼───────────────────┤
   UNAWARE OF   │  DÉNI          │  ABÎME            │
   IT           │  (unknown      │  (unknown         │
                │   known)       │   unknown)        │
                └────────────────┴───────────────────┘
```

## Mapping insight-forge entries to quadrants

| Quadrant | Insight-forge signature | Why |
|---|---|---|
| **Ancrage** | Cristallized + `counter_evidence` is concrete (not `not_explored`) + `crystallized_via` ∈ {empirical-resolution, artifact-commitment} + closure signal strong | Fact established and falsification path articulated |
| **Brouillard** | Staged with `confidence: medium` or `low`, OR cristallized with `[pending]` bindings | Acknowledged uncertainty — we know we don't know yet |
| **Déni** | Cristallized BUT `counter_evidence: not_explored` OR `[pending]` everywhere OR `crystallized_via: topic-abandonment` (silence ≠ truth) | Confident-looking entry that has no falsification path. Most dangerous category. |
| **Abîme** | What never appeared in any session — by definition not in the knowledge base | The 6-axis sweep is how we probe this quadrant |

The **Déni** quadrant is the one this skill exists to surface. A claim with `counter_evidence: not_explored` is exactly a "unknown known" — the project is operating on it, nobody has questioned it, and the pipeline's only signal that it's risky is one warning line in the run summary.

## Rules for tagging

The pipeline can compute a `quadrant` field for any entry, but does not write it eagerly to disk. Instead, the proposal generator and the council mode use it as a routing signal.

```python
def compute_quadrant(entry: dict) -> str:
    """Return 'ancrage' | 'brouillard' | 'deni' | 'abime'."""
    if not entry.get("crystallized_via"):
        # Still staged
        confidence = entry.get("confidence", "medium")
        if confidence in ("medium", "low"):
            return "brouillard"
        return "brouillard"  # default for staged
    
    counter = entry.get("counter_evidence", "")
    has_real_counter = counter and counter not in ("not_explored", "none-applicable", "")
    has_real_proof = entry.get("proof", "[pending]") not in ("[pending]", "", None)
    via = entry.get("crystallized_via", "")
    
    if has_real_counter and (via in ("empirical-resolution", "artifact-commitment") or has_real_proof):
        return "ancrage"
    
    if not has_real_counter and via == "topic-abandonment":
        # Crystallized only because nobody pushed back — pure déni
        return "deni"
    
    if not has_real_counter:
        return "deni"
    
    return "brouillard"  # has counter but no proof yet
```

`Abîme` is never assignable from existing entries — it's the gap, surfaced via the 6-axis sweep (see `devils-advocate.md`).

## Use in modes

### `/insight-forge` (default proposal)

When generating `proposals/<date>.md`, group suggestions by quadrant:

- **Ready to promote to CLAUDE.md/AGENTS.md**: entries in `Ancrage` only
- **Suggested with caveats**: entries in `Brouillard` (note the gap)
- **Should be challenged before adoption**: entries in `Déni` ← never copy-paste these directly

This single re-grouping changes the risk profile of the proposal: today, all crystallized entries get suggested with equal weight; with the quadrant tag, the `Déni` ones are flagged for council before adoption.

### `/insight-forge --challenge`

Prioritize the **Déni** quadrant. These are entries where the pipeline auto-promoted on a soft signal (typically topic-abandonment) without any falsification work. They benefit most from the 6-axis sweep.

Schedule:
1. All `Déni` entries — full sweep
2. All `Brouillard` entries with no recent reference — sweep on the strongest 2 axes
3. `Ancrage` entries — skip unless > 90 days old (sanity check for drift)

### `/insight-forge --council <id>`

The council mode (see `council-protocol.md`) explicitly takes a single entry — usually one in `Déni` or `Brouillard` that the user has flagged as high-stakes — and submits it to 5 incompatible attackers.

`Ancrage` entries can also go to council, but the test there is "is the bedrock actually bedrock?" rather than "is this premature?".

## Anti-pattern: lazy quadrant assignment

The quadrant tag is meant to surface tension, not to be performed. Bad behaviors to avoid:

- Auto-marking everything `Brouillard` to look humble — that hides the actual `Déni` cases
- Auto-marking long-running, well-cited entries `Ancrage` — `Ancrage` requires a concrete counter clause, not just usage
- Promoting from `Brouillard` to `Ancrage` just because time has passed — needs new evidence

The pipeline log should record quadrant transitions explicitly, with the trigger:

```yaml
quadrant_transitions:
  - entry: C03
    from: brouillard
    to: ancrage
    trigger: "counter_evidence updated from 'not_explored' to concrete clause via session abc12345"
    timestamp: "2026-05-03T12:00:00Z"
```

This audit trail is the only honest way to track epistemic progress in the project's knowledge base.

## Why orthogonal to type matters

Without this axis, two failure modes are invisible:

1. **A `claim` with `status: supported` looks the same in `claims.md` whether its proof is concrete (Ancrage) or its counter is `not_explored` (Déni).** Same markdown, vastly different risk.
2. **A `dead_end` that's actually `Déni`** (we declared it dead but never explored why) can be revived later under conditions we never articulated. Without the quadrant tag, it sits next to legitimate dead_ends and gets equal weight.

The connu-inconnu method's contribution to insight-forge is precisely this: forcing us to name when we're confident vs. when we're confident-looking.
