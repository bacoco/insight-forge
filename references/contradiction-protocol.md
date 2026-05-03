# Contradiction Protocol

When new events from this run contradict already-staged or already-crystallized entries, the pipeline must surface the conflict — never silently overwrite.

## Detection

A contradiction exists when:

| Existing entry | New event | Conflict type |
|---|---|---|
| Crystallized claim `C{XX}` says "X is true" | New event observes "X is false" | `claim-refuted` |
| Crystallized heuristic `H{XX}` says "always do Y" | New event shows Y backfiring | `heuristic-violated` |
| Crystallized `dead_end D{XX}` says "approach Z fails" | New event shows Z working | `dead_end-resurrected` |
| Staged observation `O{XX}` content | New event has incompatible content on same topic | `observation-conflicting` |

## Detection algorithm

For each new event from the harvester (Stage 1 output):

1. Extract the topic = longest non-trivial noun phrase from `content`
2. Search:
   - `logic/claims.md` for any claim whose `Tags` or `Statement` mentions the topic
   - `logic/heuristics.md` similarly
   - `logic/dead_ends.md` similarly
   - `staging/observations.yaml` for observations whose `content` mentions the topic
3. For each match, run a lightweight semantic compatibility check:
   - Same polarity? (both positive, both negative)
   - Same scope? (same project file, same module, same condition)
4. If incompatible → flag

Use `[CONFLICT]` markers, never delete the existing entry.

## Handling

When a conflict is detected:

1. **Do not overwrite either side.**

2. **Annotate both sides with the conflict reference.**
   - In markdown: append `<!-- CONFLICT: see {other-id} (run {YYYY-MM-DD}) -->` next to the entry
   - In YAML: add `# CONFLICT: see {other-id} (run {YYYY-MM-DD})` as a comment line

3. **Append an unresolved decision node** to `trace/exploration_tree.yaml`:
   ```yaml
   - id: N{XX}
     type: decision
     title: "Unresolved contradiction: {topic}"
     status: unresolved
     description: >
       New event from session {session_id} contradicts existing {entry_type} {entry_id}.
       Existing claim: {summary}
       New evidence: {summary}
     conflict_with: [{existing_id}, {new_event_id}]
     provenance: {whoever introduced the new event}
     timestamp: "{YYYY-MM-DDTHH:MM}"
   ```

4. **Surface in run summary**:
   ```
   [insight-forge] ... 1 contradiction flagged: see proposals/contradictions-{date}.md
   ```

5. **Generate a contradiction memo** at `proposals/contradictions-{date}.md`:
   ```markdown
   # Contradictions detected on {date}

   ## C{XX} vs new evidence (session {sid})

   **Existing claim**: {full statement}
   **Crystallized via**: {signal}, {date}
   **Counter-evidence at promotion**: {original counter_evidence}

   **New evidence**:
   {quote from session, with session/turn ref}

   **Suggested resolutions** (pick one or write your own):
   - [ ] Update C{XX} status → `weakened` or `refuted`
   - [ ] Promote new evidence to a competing claim
   - [ ] Mark scope: original valid in context A, new evidence in context B
   - [ ] Discard new evidence as noise (explain why)
   ```

The user reads this memo and decides. The pipeline never auto-resolves.

## Special cases

### Crystallized → refuted by new evidence

This is the most common and most valuable contradiction. The original claim is NOT deleted. Its status moves to `weakened` (one refuting case) or `refuted` (multiple refuting cases or definitive proof). The original `counter_evidence` field is updated to reference the actual refuting evidence (instead of the speculative version generated at promotion).

If the entry was a `dead_end` and new evidence shows it actually works → **do not delete the dead_end**. Mark `status: revised` and add a `revival_conditions` field describing what changed (different version of dependency, different OS, etc.). The lesson stays valuable as "didn't work in conditions Y" even when "works in conditions Y'".

### Two new events contradict each other (same run)

Stage both. Add cross-reference `# CONFLICT: see O{YY}` to each. Do NOT crystallize either until the conflict is resolved by user input or by a clear empirical resolution in a future session.

### Disputed by user mid-session

If the user explicitly says "that's wrong" / "no, that's not right" about an assistant claim:
- Tag the original `disputed`
- Do NOT auto-flip provenance
- Generate an `unresolved` decision node so the user can adjudicate later

The user's "wrong" might itself be incorrect — humans get things wrong too. The pipeline records the disagreement, doesn't pick a winner.

## Anti-pattern: silent merging

The temptation when a new event "extends" an old claim is to merge them. **Don't.** Generate a new entry that cites the old one as a dependency. Let the user decide if the old one should be archived. Merging silently destroys the audit trail.

Example:
- C03: "Tests fail on Python 3.10" (date X, supported)
- New evidence: tests also fail on Python 3.9

WRONG: edit C03 to say "Tests fail on Python 3.9 and 3.10"
RIGHT: create C07 "Tests fail on Python 3.9", with `dependencies: [C03]`. Both stand. User can later collapse if they want.
