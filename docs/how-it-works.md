# How insight-forge works — algorithm walkthrough

End-to-end map of what happens when a user types `/insight-forge`, with file
paths and function names so you can read the code as you read this.

If you came from the README and just want the broad shape, jump to
[Carte des fichiers clés](#carte-des-fichiers-clés) at the bottom.

---

## Étape 0 — Entrée utilisateur

```
User tape /insight-forge
        ↓
Claude Code / Codex CLI charge SKILL.md, lit le frontmatter,
déclenche le skill (uniquement sur les triggers exacts du frontmatter)
        ↓
Le skill instruit l'agent : "lance python3 scripts/run.py"
```

**Fichiers** : `SKILL.md` (frontmatter ligne 1-3, *Per-Run Procedure* ligne ~57)

---

## Étape 1 — Orchestration

**`scripts/run.py:main()`** — l'unique entry point côté code.

```text
1.  lit .insight-forge/.last_run            → read_last_run()
       └─ curseur incrémental ; absent au 1er run
2.  détecte les agents présents             → detect_agents()
       ~/.claude/projects/   → "claude"
       ~/.codex/sessions/    → "codex"
       absent → empty-state guidance + exit 1
3.  pour chaque agent : extraction          → extract()
       passe --since=<curseur> → seules les sessions modifiées après sont lues
4.  merge des sorties si deux agents        → merge_normalized()
5.  pipeline                                 → subprocess pipeline.py
6.  proposal                                 → subprocess propose_claude_md.py
       (la stderr du subprocess flow direct → user voit le résumé sympa)
7.  met à jour .last_run                    → ts UTC + last_session
```

---

## Étape 2 — Extraction (par agent)

**`scripts/extract_claude.py:main()`** et son jumeau `extract_codex.py`.

```text
1.  encode le cwd projet → nom de dossier ~/.claude/projects/<encoded-cwd>
2.  globe les *.jsonl, sort par mtime
3.  filtre par --since (timestamp .last_run, normalisé en UTC tz-aware)
4.  pour chaque fichier JSONL, parse ligne par ligne :
       filtre les <system-reminder>, hooks, skill-loading, bash-input
       émet pour chaque tour utile :
          {role, content, timestamp, tool_name, tool_status, session_id, ...}
       borne la session par {_marker: "session_start"} et {_marker: "session_end"}
5.  écrit le tout dans .insight-forge/.cache/normalized_<agent>.jsonl
```

C'est le **format pivot** — la même structure quel que soit l'agent source. Les
deux extractors sont les seuls fichiers qui connaissent les spécificités de
chaque format JSONL ; tout le reste du pipeline lit le pivot.

Spec des deux formats : `references/claude-code-format.md`, `references/codex-format.md`.

---

## Étape 3 — Pipeline ARA (le cœur)

**`scripts/pipeline.py:run_pipeline()`** — 3 étages séquentiels.

### Étage 1 — Context Harvester

**`harvest(normalized_path)`**

```text
pour chaque ligne de normalized.jsonl :
   si _marker == "session_start" → ouvre une session, accumule les events
   si _marker == "session_end"   → flush_session()
flush_session() :
   pour chaque event i de la session :
      construit un CandidateEvent avec
         prev_role / prev_content (event i-1)
         next_role / next_content (event i+1)
   → fournit au router une fenêtre de contexte ±1 tour
```

Sortie : `list[CandidateEvent]` + métadonnées par session.

### Étage 2 — Event Router

**`classify_and_route(ev)`** — décide *quoi faire* de chaque candidat. Ordre de
priorité strict (le premier qui match gagne) :

```text
1. hard skips (vide, role==system, < 3 chars)
2. dead_end          (role=user, contient une DEAD_END_PHRASES)         → direct
3. tool error        (role=tool_result, tool_status=error)              → staged
4. pivot             (role=user, contient une PIVOT_PHRASES)            → direct
5. ┌─ rule engine ── harness/loader.py:classify_with_rules() ──────┐
   │   parcourt harness/rules.yaml dans l'ordre :                  │
   │     R-HEURISTIC-ALWAYS-NEVER (when matches → emit)            │
   │     R-CONSTRAINT-MUST-REQUIRES (when matches AND not unless)  │
   │     R-CLAIM-ASSISTANT (when matches AND not META_WORK_PREFIX) │
   │   première règle qui fire → retourne le emit                  │
   └──────────────────────────────────────────────────────────────┘
6. decision          (role=user, regex "let's go with X")               → direct
7. experiment        (tool_use Edit/Write/MultiEdit/...)                → direct
8. question          (role=user finissant par "?", suivi d'une question) → direct
sinon → drop (return None)
```

`direct` = écrit immédiatement dans `trace/exploration_tree.yaml`.
`staged` = écrit dans `staging/observations.yaml`, attend une cristallisation.

### Étage 3 — Maturity Tracker

**`evaluate_maturity(obs, candidates, sessions)`** — pour chaque observation
staged, teste les 4 signaux de clôture **dans cet ordre**, et garde le premier
qui fire :

```text
si obs.promoted == True → skip (déjà cristallisée)

signal 1 — verbal-affirmation               detect_verbal_affirmation()
    cherche dans les 3 prochains tours user de la même session
    une phrase de AFFIRMATION_PHRASES sans hedging ("maybe", "peut-être")

signal 2 — empirical-resolution             detect_empirical_resolution()
    pour les 5 prochains tool_result de la même session :
       vérifie chevauchement de mots-clés ≥4 chars avec obs.content
       si tool_status == "ok"     → "supported"  → crystallise comme claim
       si tool_status == "error"  → "refuted"    → crystallise comme dead_end

signal 3 — topic-abandonment                detect_topic_abandonment()
    extrait 5 mots-clés (≥5 chars) de obs.content
    prend les k=5 sessions les plus récentes hors session d'origine
    si AUCUNE ne mentionne un mot-clé → topic abandonné → crystallise

signal 4 — artifact-commitment              (TODO, pas implémenté)

aucun signal → reste en staging, et marque comme "stale" si > 14 jours
```

Quand un signal fire :

```text
1. génère counter_evidence (Devil's Advocate)        generate_counter_evidence()
2. write_<layer>(state, new_id, fields)               écrit logic/<layer>.md
3. write_evidence_bundle(state, new_id, ...)         écrit evidence/bundles/<id>.yaml
       capture la quote du trigger (l'observation d'origine)
       capture la quote de la closure (verbal-affirmation, tool result, ou
       indication topic-abandonment)
4. update_observation(promoted=True, evidence_bundle=...)
```

---

## Étape 4 — Proposition CLAUDE.md / AGENTS.md

**`scripts/propose_claude_md.py:main()`**

```text
1. parse_md_entries() lit logic/heuristics.md, claims.md, dead_ends.md
   → liste de dicts {id, title, Rule, Counter-cases, Sessions, ...}

2. pour chaque entrée :
      _bundle_quotes(forge_dir, entry_id) lit evidence/bundles/<id>.yaml
      → splice "*You said* (date): «...»" et "*You confirmed* ...«...»"
        dans la proposition markdown
      → l'utilisateur voit ses propres mots dans la proposition

3. écrit .insight-forge/proposals/<UTC-timestamp>.md
4. _print_summary() écrit le digest human-friendly sur stderr :
       ✓ N project rules ready
       ✗ M dead ends to avoid
       · K observations still in staging
5. imprime le chemin de la proposition sur stdout (contrat pour run.py)
```

L'agent ne touche **jamais** à `CLAUDE.md` / `AGENTS.md` directement. Le diff
attend dans `.insight-forge/proposals/` ; l'utilisateur copie ce qu'il veut.

---

## Où vivent les techniques des deux papiers

Les deux papiers académiques cités dans le README ne sont pas décoratifs. Voici
où exactement chaque concept est implémenté.

### Tsinghua — *Natural-Language Agent Harnesses* (Pan et al., 2026)

> Externaliser la logique de contrôle comme artefact portable, éditable, avec
> contrats explicites et artefacts durables.

| Concept du papier | Fichier | Fonction / structure |
|---|---|---|
| Harness comme **donnée portable** | `harness/rules.yaml` | (le fichier YAML lui-même — la logique de Stage 2 vit là, plus dans le code) |
| Loader du spec | `harness/loader.py` | `load_rules()` — parse rules.yaml en `RuleSet` |
| Évaluateur de prédicats | `harness/loader.py` | `_matches()`, `_check_atom()` — implémente AND / `any:` / `all:` + tous les prédicats |
| Classifieur runtime | `harness/loader.py` | `classify_with_rules(ev, ruleset)` |
| Intégration au pipeline | `scripts/pipeline.py` | `_get_ruleset()` (lazy load + override `INSIGHT_FORGE_RULES_PATH`), appel dans `classify_and_route()` |
| **Contrats explicites** | `harness/rules.yaml` | bloc `contract: must_fire_on / must_not_fire_on` sur chaque règle |
| Vérificateur de contrats | `scripts/run_evals.py` | `verify_rule_contracts()` (mode `--verify-contracts`) |
| **Artefacts durables** | `scripts/pipeline.py` | `write_evidence_bundle()` — écrit `evidence/bundles/<id>.yaml` à chaque cristallisation |
| Schema des bundles | `harness/proposals/README.md` + sortie de `write_evidence_bundle` | `entry_id`, `target_layer`, `crystallized_via`, `evidence[]` (trigger + closure quotes), `counter_evidence`, `promotion_gate` |
| Surface utilisateur | `scripts/propose_claude_md.py` | `_load_bundle()` + `_bundle_quotes()` — re-lit les bundles pour splicer les quotes dans la proposition |

**Test de la propriété :** modifie une règle dans `harness/rules.yaml`, lance
`python3 scripts/run_evals.py --verify-contracts`. Si tu casses un contrat,
le script imprime `✗ <rule_id>: must_not_fire_on=<fixture> but matched an event`
et exit 1. Tu peux éditer le harness sans toucher au Python — exactement la
propriété que le papier réclame.

### Stanford — *Meta-Harness: End-to-End Optimization of Model Harnesses* (Lee et al., 2026)

> Une fois que le harness est de la donnée avec des contrats mesurables, un
> proposer agentique peut éditer le spec et se noter par le delta d'eval.

| Concept du papier | Fichier | Fonction / structure |
|---|---|---|
| Substrat d'éval mesurable | `evals/fixtures/*.jsonl` + `evals/expected/*.yaml` | (les fixtures sont les contrats ; les expected.yaml sont les vérités) |
| Driver d'évaluation | `scripts/run_evals.py` | `run_pipeline_on_fixture()` — passe `INSIGHT_FORGE_RULES_PATH` au subprocess pour sandboxer un candidat |
| Métriques | `scripts/run_evals.py` | `aggregate_metrics()` — `false_promotion_rate`, `missed_promotion_rate`, `provenance_coverage` |
| **Proposer** | `scripts/propose_rules.py` | `main()` (orchestration) + `extract_candidate_phrases()` (génération de candidats) |
| Mutation operator | `scripts/propose_rules.py` | `mutation_regex_alternation_extend()` — ajoute un terme à l'alternation regex d'une règle |
| **Sandbox** | `scripts/propose_rules.py` | `make_candidate_rules()` (clone le spec) → écrit dans `/tmp` → `score_candidate()` lance `run_evals.py --rules-path` |
| **Scoring eval-graded** | `scripts/propose_rules.py` | `score_candidate()` : `+1` par gap fixture fermé, `-∞` par régression ou violation de contrat |
| Marquage des gaps | `evals/expected/<fixture>.expected.yaml` | champs `known_gap: true` + `target_rule: R-...` |
| Skip des gaps en régression | `scripts/run_evals.py` | gate dans la boucle `main()` qui sépare `gap_results` des `results` |
| **Sortie reviewable** (jamais auto-apply) | `scripts/propose_rules.py` | `write_proposal()` → `harness/proposals/<ts>-<rule>.yaml` avec `before` / `after` / `metric_delta` / `apply_instructions` |
| Gitignore des outputs | `harness/proposals/.gitignore` | (proposals = artefacts par utilisateur, pas dans git) |

**Test de la boucle :** marque un fixture comme `known_gap: true` + nomme un
`target_rule:`, lance `python3 scripts/propose_rules.py`. Le script extrait
des phrases candidates, sandbox-évalue chaque mutation, écrit la meilleure
dans `harness/proposals/`. Aucun `rules.yaml` n'est modifié dans le repo —
exactement la garantie du papier (proposer + eval-graded + reviewable).

**Le seam swappable.** La fonction `mutation_regex_alternation_extend` dans
`propose_rules.py` est la seule chose à remplacer pour brancher un proposer
LLM. Tout le reste — sandboxing, scoring, écriture de proposition, scoring
contre régressions et contrats — reste identique.

---

## Carte des fichiers clés

| Concept | Fichier | Fonction-clé |
|---|---|---|
| Entry point | `scripts/run.py` | `main()` |
| Format pivot | `scripts/extract_*.py` | `main()` |
| Stage 1 (harvester) | `scripts/pipeline.py` | `harvest()` |
| Stage 2 (router) | `scripts/pipeline.py` | `classify_and_route()` |
| Règles dispatchées | `harness/loader.py` | `classify_with_rules()` |
| Spec des règles | `harness/rules.yaml` | (data, pas code) |
| Stage 3 (maturity) | `scripts/pipeline.py` | `evaluate_maturity()` |
| 4 signaux de clôture | `scripts/pipeline.py` | `detect_verbal_affirmation()`, `detect_empirical_resolution()`, `detect_topic_abandonment()` |
| Devil's Advocate | `scripts/pipeline.py` | `generate_counter_evidence()` |
| Bundle de preuve | `scripts/pipeline.py` | `write_evidence_bundle()` |
| Proposition CLAUDE.md | `scripts/propose_claude_md.py` | `build_proposal()` + `_print_summary()` |
| Contrats vérifiables | `evals/expected/*.yaml` | (data) |
| Test de régression | `scripts/run_evals.py` | `verify_rule_contracts()` + `compare()` |
| Proposer de règles | `scripts/propose_rules.py` | `score_candidate()` (boucle sandbox) |

---

## Une phrase par étage

- **Harvester** : lit JSONL → events typés avec contexte ±1
- **Router** : `if dead_end / pivot / tool_use → direct ; sinon rules.yaml dispatche heuristic / claim / constraint → staged`
- **Maturity Tracker** : pour chaque staged, fire le **premier** des 4 signaux qui matche, sinon laisse en staging
- **Proposer (CLAUDE.md)** : lit logic + bundles → splice les citations → markdown reviewable, jamais auto-appliqué
- **Proposer (rules.yaml)** : génère mutations → sandbox-évalue → écrit le meilleur dans `harness/proposals/`, jamais auto-appliqué
