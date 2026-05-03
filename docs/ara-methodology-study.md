# Étude : Adaptation de la méthodologie ARA pour un skill d'auto-amélioration des sessions Claude

> **TL;DR** — Le papier *Agent-Native Research Artifact* (Orchestra Research, arXiv 2604.24658) propose un protocole pour transformer la trajectoire de recherche en artefact machine-exécutable. Sa pièce maîtresse, le **Live Research Manager**, est un *end-of-turn recorder* qui capture décisions, dead-ends et heuristiques avec **provenance tags** et **progressive crystallization**. Cette mécanique est directement transposable à un autre problème : l'amélioration continue des sessions Claude. Le skill proposé — `session-optimizer` — applique le même pipeline (Context Harvester → Event Router → Maturity Tracker), mais en **mode rétroactif** sur des JSONs de session, avec pour livrable des updates ciblés au prompting de Claude (CLAUDE.md, mémoires, préférences).

---

## Sommaire

1. [Pourquoi la méthodologie ARA est un trésor pour ton problème](#1)
2. [Disséquer ARA : les sept idées clés à transposer](#2)
3. [Le mapping ARA → sessions Claude](#3)
4. [Architecture du skill `session-optimizer`](#4)
5. [Pipeline détaillé en cinq étages](#5)
6. [Schémas et structures de fichiers](#6)
7. [Closure signals adaptés aux sessions Claude](#7)
8. [Workflow d'utilisation et boucles de feedback](#8)
9. [Considérations critiques et garde-fous](#9)
10. [Plan d'implémentation par phases](#10)
11. [Annexes : exemples concrets](#11)

---

<a id="1"></a>
## 1. Pourquoi la méthodologie ARA est un trésor pour ton problème

### 1.1 Le constat ARA, mot à mot

Le papier ouvre sur deux taxes structurelles que paie toute recherche scientifique quand elle est compilée en narration linéaire (le PDF) :

- **Storytelling Tax** — Les essais ratés, les hypothèses rejetées et les pivots disparaissent. Les chiffres : sur 24 008 runs d'agents sur RE-Bench, **90,2 % du coût dollar total est dépensé sur des runs ratés** que le papier final ne mentionne jamais. Le ratio médian *failed-to-success* en tokens est de **113×**. Conséquence directe : chaque équipe redécouvre en moyenne 113× le même cul-de-sac.
- **Engineering Tax** — Sur 8 921 exigences de reproduction expertement annotées (PaperBench), seulement **45,4 % sont entièrement spécifiées dans le PDF source**. Le reste vit dans le repo, dans la tête du chercheur, ou nulle part.

ARA résout ces deux problèmes en remplaçant le PDF par un *artefact* en quatre couches : `/logic` (le quoi & pourquoi), `/src` (le comment), `/trace` (le voyage avec les dead-ends préservés), `/evidence` (les preuves brutes).

### 1.2 Pourquoi ça résonne avec les sessions Claude

Une session Claude est, structurellement, **une trajectoire de recherche/travail**. Elle a exactement les mêmes pathologies :

| Pathologie ARA (recherche) | Équivalent dans une session Claude |
|---|---|
| Dead-ends jamais documentés | Tu re-expliques 5× à Claude que tu n'aimes pas les bullet points |
| 90,2 % du coût en runs ratés | Tu reformules ta question 3× parce que Claude fait le mauvais choix par défaut |
| 45,4 % de spec manquante | CLAUDE.md ne dit rien sur ton stack, ton style, tes contraintes |
| Tacit knowledge non-captée | Tu corriges Claude sur le même travers à chaque nouvelle session |
| Pas de provenance | Tu ne sais plus si "Claude doit toujours faire X" vient de toi ou d'une suggestion qu'il t'a faite |

**La thèse** : si ARA marche pour la recherche scientifique, le même protocole — *capture structurée, provenance, crystallization sous signal* — peut transformer chaque session Claude (déjà *born textual*) en données d'amélioration pour la suivante.

Le papier le dit lui-même (§3.1) : *"AI-native research dissolves this barrier: the process trace is not an additional deliverable but a byproduct of the research itself, generated automatically in every researcher–agent session."* Remplace "research" par "interaction utilisateur" et tu as exactement ton cas.

### 1.3 Ce que tu gagnerais concrètement

Trois bénéfices tangibles, par ordre de magnitude :

1. **Élimination des frictions récurrentes** — Les corrections que tu fais à Claude session après session sont identifiées, agrégées, et migrées dans CLAUDE.md ou dans tes préférences. Tu ne les fais plus.
2. **Mémoire des dead-ends** — Quand Claude a essayé une approche qui n'a pas marché pour un type de problème, c'est tagué et évité la fois suivante.
3. **Crystallisation des préférences réelles** — Tes goûts (ton, format, longueur, niveau de technicité, langues) sont extraits empiriquement de ce que tu *fais* (corriges, valides, abandonnes), pas seulement de ce que tu *déclares*. C'est ça la vraie valeur — la préférence révélée bat la préférence déclarée.

---

<a id="2"></a>
## 2. Disséquer ARA : les sept idées clés à transposer

J'extrais ici les sept primitives de design qui font la puissance d'ARA. Chacune est transposable ; certaines plus directement que d'autres.

### 2.1 Les quatre couches comme ontologie

ARA refuse l'idée d'un "fichier qui contient tout". Il sépare quatre types de connaissance qui ont des structures fondamentalement différentes :

- **Cognitive** (`/logic`) — stable, citable, version-trackée
- **Physique** (`/src`) — itère continuellement, exécutable
- **Trace** (`/trace`) — branchue, chronologique, avec dead-ends
- **Évidence** (`/evidence`) — précise, machine-readable, immuable

**Transposition** : pour les sessions Claude, on a les mêmes quatre catégories qui méritent d'être séparées, avec des étiquettes adaptées (voir §3).

### 2.2 Provenance tags

Chaque entrée porte un tag : `user`, `ai-suggested`, `ai-executed`, `user-revised`. C'est génial parce que ça empêche Claude (ou le chercheur) de confondre *ce que j'ai dit* avec *ce que l'IA a inféré* avec *ce qu'on a confirmé ensemble*.

**Règle d'or ARA** : *un événement `ai-suggested` n'est jamais auto-promu en `user-revised`. Il faut une affirmation explicite.*

**Transposition** : crucial pour ton cas. Si Claude analyse une session et "voit" que tu préfères les réponses courtes, c'est `claude-inferred`. Si tu lui as dit "fais des réponses courtes", c'est `user-stated`. Ces deux tags ne donnent PAS le même poids dans la décision d'updater CLAUDE.md.

### 2.3 Progressive crystallization

C'est *la* trouvaille qui distingue ARA des approches naïves. Les observations sont **stagées** d'abord (dans `staging/observations.yaml`) et **crystallisées** ensuite, mais seulement si un signal de fermeture apparaît. Pas de compteur. Pas de jugement par LLM. Quatre signaux discrets et observables :

1. **Topic abandonment** — pas mentionné depuis k=5 turns
2. **Verbal affirmation** — l'utilisateur dit "yes" / "exactly" / "ship it"
3. **Empirical resolution** — une expérience résout
4. **Artifact commitment** — du code mergé, une décision référencée comme evidence

**Pourquoi c'est génial** : ça empêche la *crystallisation prématurée*, qui est exactement le travers d'un système naïf de mémorisation. Un système naïf voit "user said X" et écrit immédiatement "user prefers X" dans la mémoire. Trois sessions plus tard, tu te retrouves avec un CLAUDE.md plein de fausses préférences.

**Transposition** : on garde *exactement* cette mécanique, avec des signaux adaptés (voir §7).

### 2.4 Dead-ends comme citoyens de première classe

Dans `/trace/exploration_tree.yaml`, les nodes peuvent être de cinq types : `question`, `decision`, `experiment`, `dead_end`, `pivot`. Chaque dead_end porte trois champs :

- `hypothesis` : ce qu'on a essayé
- `failure_mode` : pourquoi ça a échoué
- `lesson` : ce qu'on en tire

**Transposition** : un "dead-end" dans une session Claude, c'est une approche que tu as essayée et abandonnée. Exemple : "Claude m'a généré un script Python avec asyncio, j'ai dit que je voulais du sync, on a redémarré." Ça doit être capturé, parce que la fois prochaine, sur un projet similaire, Claude doit le savoir.

### 2.5 Forensic bindings

Chaque claim référence ses preuves. Chaque heuristique référence le code. Chaque décision référence l'évidence. C'est typé, c'est navigable, c'est vérifiable.

**Transposition** : pour les sessions Claude, on lie chaque "préférence détectée" aux **turns spécifiques** où elle a été observée. Ça donne :
- Traçabilité (le user peut auditer)
- Annulabilité (si la préférence est mauvaise, on remonte aux preuves)
- Confiance graduée (3 occurrences ≠ 1 occurrence)

### 2.6 Progressive disclosure

`PAPER.md` (~200 tokens) suffit à un agent pour décider si l'artefact est pertinent. Le reste se charge à la demande. C'est le `README.md` du futur.

**Transposition** : `claude-meta/README.md` doit en ~300 tokens donner à Claude (au démarrage de session) l'essentiel : *qui es-tu utilisateur, quel projet, quelles préférences fortes*. Le reste se charge si Claude en a besoin.

### 2.7 Trois étages : Context Harvester → Event Router → Maturity Tracker

Ce pipeline en trois étapes est l'épine dorsale du Research Manager. Chaque étape a une responsabilité unique :

- **Harvester** : *qu'est-ce qui s'est passé ?* (extraction brute)
- **Router** : *à quoi ça correspond ?* (classification + provenance + routing direct/staged)
- **Tracker** : *est-ce mûr pour passer en typed knowledge ?* (closure signals)

**Transposition** : on conserve cette tripartition. C'est elle qui rend le système gérable et auditable.

---

<a id="3"></a>
## 3. Le mapping ARA → sessions Claude

Voici la table de traduction, terme à terme, qui doit guider toute la conception du skill.

| Concept ARA | Équivalent skill `session-optimizer` |
|---|---|
| `ara/` directory | `claude-meta/` directory |
| `PAPER.md` (manifest) | `claude-meta/README.md` (synthèse user + projet) |
| `/logic/claims.md` | `/logic/preferences.md` (préférences crystallisées) + `/logic/domain_facts.md` (faits stables sur le user/projet) |
| `/logic/heuristics.md` | `/logic/instructions.md` (instructions à pousser dans CLAUDE.md) + `/logic/anti_patterns.md` (ce que Claude ne doit PAS faire) |
| `/logic/concepts.md` | `/logic/glossary.md` (terminologie spécifique au user) |
| `/src/configs/` | `/proposed/claude_md_diff.md` (diff de config proposé) + `/proposed/memory_candidates.yaml` |
| `/trace/exploration_tree.yaml` | `/trace/sessions_dag.yaml` (le DAG des projets/threads/décisions inter-sessions) |
| `/trace/sessions/YYYY-MM-DD_NNN.yaml` | identique : un fichier par session JSON analysée |
| `/trace/pm_reasoning_log.yaml` | `/trace/optimizer_reasoning_log.yaml` (auto-continuité) |
| `/staging/observations.yaml` | identique : tampon de crystallisation |
| `/evidence/` | `/evidence/turn_excerpts.yaml` (extraits exacts des turns qui supportent une crystallisation) |
| Provenance: `user`, `ai-suggested`, `ai-executed`, `user-revised` | Provenance: `user-stated`, `user-corrected`, `user-affirmed`, `claude-inferred`, `pattern-derived` |
| Closure: abandonment / affirmation / empirical / commitment | Closure: recurrence-k / affirmation / correction-stable / preference-revealed |
| Event types: `decision`, `experiment`, `dead_end`, `pivot`, `claim`, `heuristic`, `observation` | Event types: `friction`, `correction`, `preference`, `dead_end`, `pivot`, `praise`, `instruction`, `domain_fact`, `tool_issue`, `meta_request` |

L'idée centrale : **on garde l'ossature ARA exacte** ; on **renomme** ce qui doit l'être ; on **enrichit** la taxonomie d'événements pour coller au domaine "interaction utilisateur ↔ Claude" plutôt que "chercheur ↔ agent de codage".

---

<a id="4"></a>
## 4. Architecture du skill `session-optimizer`

### 4.1 Principes de design

Cinq principes que je dérive directement d'ARA et adapte :

1. **Mode rétroactif, pas in-line.** Le `research-manager` original tourne *à chaque end-of-turn*. Ton cas est différent : tu veux une analyse périodique (1×/jour ou à la demande) sur des sessions déjà closes. C'est plus simple, plus économe, et permet du multi-session pattern detection.
2. **Multi-session par défaut.** Une seule session ne suffit pas pour identifier un pattern. La force du skill vient du *cross-session*. Le skill traite donc un *batch* de sessions à chaque run.
3. **Read-only sur les sessions, write-only sur l'artefact.** Le skill ne modifie *jamais* les JSONs de session (sources de vérité immuables). Il n'écrit que dans `claude-meta/`.
4. **Validation explicite avant injection.** Le skill ne touche *jamais* directement à CLAUDE.md ou aux mémoires. Il produit des *propositions* dans `/proposed/`, le user valide.
5. **Auto-continuité.** Comme le `pm_reasoning_log.yaml` du Research Manager, le skill garde une trace de ses propres décisions organisationnelles, ce qui lui évite la dérive d'un run à l'autre.

### 4.2 Surface d'invocation

Trois modes :

```
/session-optimizer                      # mode auto : trouve les sessions non analysées et les traite
/session-optimizer path/to/session.json # une session spécifique
/session-optimizer --since 2026-04-01   # batch sur fenêtre temporelle
/session-optimizer --review             # ne traite rien, ouvre le briefing avec les staged candidates
/session-optimizer --crystallize        # walk staging/, vérifie les closure signals, crystallise
```

### 4.3 Inputs attendus

Trois sources possibles :

- **Exports JSON Claude.ai** — format conversation
- **Sessions Claude Code** — JSON line-delimited dans `~/.claude/projects/*/`
- **Transcripts génériques** — n'importe quel JSON conversationnel mappable

Le skill normalise vers un schéma interne unique avant traitement.

### 4.4 Outputs

Trois livrables, dans l'ordre d'importance :

1. **`claude-meta/`** — l'artefact versionné (le contrat de mémoire long terme)
2. **`claude-meta/proposed/`** — les diffs prêts à être pushés vers CLAUDE.md, le système de mémoire, ou les préférences
3. **`claude-meta/briefing.md`** — un rapport human-readable (1-3 pages) de ce qui a été détecté ce run

### 4.5 Diagramme de flux global

```
        ┌──────────────────────────────────────────────────────────────────┐
        │                     /session-optimizer (invoke)                  │
        └───────────────────────────────┬──────────────────────────────────┘
                                        │
                ┌───────────────────────┴────────────────────────┐
                │                                                │
       ┌────────▼────────┐                              ┌────────▼─────────┐
       │ Discovery       │  ──── trouve sessions ───►   │ session_index    │
       │ (scan filesys)  │                              │ vérifie déjà-vu  │
       └────────┬────────┘                              └────────┬─────────┘
                │                                                │
                │      ┌─────────────────────────────────────────┘
                │      │
                ▼      ▼
       ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
       │  Context Harvester │→ │   Event Router     │→ │  Pattern Detector  │
       │  (par session)     │  │  (classify+route)  │  │  (cross-session)   │
       └────────────────────┘  └────────────────────┘  └────────┬───────────┘
                                                                │
                                                                ▼
                                                       ┌────────────────────┐
                                                       │  Maturity Tracker  │
                                                       │  (closure signals) │
                                                       └────────┬───────────┘
                                                                │
                                                                ▼
                                                       ┌────────────────────┐
                                                       │  Proposal Synth.   │
                                                       │  (CLAUDE.md diff,  │
                                                       │   memory cands)    │
                                                       └────────┬───────────┘
                                                                │
                                                                ▼
                                                       ┌────────────────────┐
                                                       │   Briefing render  │
                                                       └────────────────────┘
```

C'est *exactement* le pipeline d'ARA, étendu d'un étage (Pattern Detector) qui est le bénéfice spécifique du mode multi-session rétroactif.

---

<a id="5"></a>
## 5. Pipeline détaillé en cinq étages

### 5.1 Étage 1 — Discovery

**Rôle** : trouver les sessions à traiter, en se basant sur un index pour ne jamais retraiter deux fois la même.

**Input** :
- Un ou plusieurs paths (dirs ou fichiers)
- Optionnellement, une fenêtre temporelle

**Output** : liste de sessions à traiter avec leurs métadonnées (date, taille, hash).

**Mécanique** :
- Lit `claude-meta/trace/sessions/session_index.yaml`
- Calcule un hash sur chaque session candidate
- Filtre celles déjà présentes dans l'index
- Trie par date

**Détail crucial** : si une session est partiellement traitée (par exemple, le run précédent a crashé), on a un flag `partial: true` dans l'index ; on reprend.

### 5.2 Étage 2 — Context Harvester

**Rôle** : pour chaque session, lire le JSON et extraire la liste plate de **candidate events**.

**Input** : une session normalisée (transcript user/assistant + tool calls + tool results).

**Output** : flat list de candidates events au format :
```yaml
- turn: 7
  speaker: user | assistant | tool
  type_hint: friction | correction | preference | dead_end | praise | ...
  raw_excerpt: "..."
  context: "..."
  surrounding_turns: [6, 7, 8]
```

**Mécanique** : c'est l'étage qui demande le plus de jugement (et où Claude excelle). On ne cherche pas à classifier ; juste à *identifier* ce qui mérite attention. Heuristiques :

- Phrases user en négatif : "non", "pas comme ça", "j'aimerais plutôt", "trop long", "tu fais toujours X"
- Phrases user de validation : "parfait", "exactement", "ship it", "c'est bon"
- Phrases user prescriptives : "à partir de maintenant", "rappelle-toi que", "toujours fais X"
- Reformulations user (le user redit la même demande différemment → friction)
- Tool errors et leur résolution
- Pivots de l'assistant suite à une remarque user
- Domain facts factuels mentionnés ("je suis dev Rust", "mon projet s'appelle Foo")

**Skip filter** (à respecter strictement, comme dans ARA) :
- Salutations
- Acknowledgments purs
- Questions de clarification sans nouvelle information

### 5.3 Étage 3 — Event Router

**Rôle** : pour chaque candidate, *classifier*, *tagger la provenance*, *distiller le payload*, et *router*.

**Décision direct vs staged** :

- **Direct** (vers `/trace/`) : événements factuels et chronologiques qui ne demandent pas d'interprétation. Exemples : `dead_end`, `pivot`, `tool_issue`, `correction` ponctuelle.
- **Staged** (vers `/staging/observations.yaml`) : événements interprétatifs qui demandent confirmation par closure signal. Exemples : `preference`, `instruction`, `domain_fact`, `claim` sur le style de Claude.

**Provenance assignment** :
- Énoncé direct par le user → `user-stated`
- User a corrigé Claude → `user-corrected`
- User a explicitement validé une suggestion de Claude → `user-affirmed`
- Inféré par observation comportementale → `claude-inferred`
- Émergé d'un pattern multi-session → `pattern-derived`

**Distillation** : transformer la prose conversationnelle en télégraphique factuel. Exemple :
- Brut : *"euh non en fait je préfère que tu me donnes des réponses plus courtes, là c'était trop long"*
- Distillé : `preference: response length: short; trigger: long response received`

**Forensic binding** : chaque entrée porte au minimum `bound_to_session` + `bound_to_turns`.

### 5.4 Étage 4 — Pattern Detector (NOUVEAU vs ARA)

C'est l'étage que j'ajoute spécifiquement pour le mode rétroactif multi-session. ARA n'en a pas besoin parce qu'il tourne en live ; nous, on a tout l'historique d'un coup.

**Rôle** : détecter les patterns récurrents à travers plusieurs sessions, y compris quand chaque occurrence individuelle est trop faible pour déclencher une crystallisation.

**Trois types de patterns** :

1. **Friction recurrente** : la même correction apparaît dans k≥3 sessions distinctes. Exemple : 4 sessions où le user dit *"trop long"*.
2. **Préférence révélée** : le user choisit systématiquement la même option quand on lui en propose plusieurs. Exemple : sur 5 occasions où Claude propose plusieurs styles, le user choisit le plus terse 5/5.
3. **Anti-pattern Claude** : Claude commet la même erreur dans des contextes similaires. Exemple : sur des questions de code Python, Claude propose toujours asyncio même quand le user ne veut pas.

**Output** : entrées dans `/staging/patterns.yaml` qui peuvent ensuite déclencher la crystallisation via le signal `recurrence-k`.

### 5.5 Étage 5 — Maturity Tracker + Proposal Synthesizer

**Rôle dual** :
- *Maturity Tracker* : walk `staging/`, vérifier les closure signals, crystalliser ce qui est mûr.
- *Proposal Synthesizer* : pour chaque crystallisation, générer une proposition concrète d'update du prompting.

**Procédure de crystallisation** (héritée d'ARA, légèrement adaptée) :

```
Pour chaque observation O en staging:
  1. Lire content, context, potential_type, provenance, bound_to.
  2. Vérifier les 4 closure signals dans l'ordre:
     a. Recurrence-k (k≥3 occurrences cross-session avec même topic)
     b. Affirmation (user a explicitement validé dans une session)
     c. Correction stable (k≥3 corrections du même travers)
     d. Preference revealed (k≥3 choix consistants)
  3. Si aucun signal: laisser staged. Stop.
  4. Si signal → allocate ID dans la couche cible.
  5. Construire l'entrée typée.
  6. Provenance upgrade: 
     - Affirmation → claude-inferred bascule en user-affirmed
     - Recurrence/Preference → bascule en pattern-derived (PAS en user-stated)
  7. Établir forensic bindings (vers les turns spécifiques qui supportent).
  8. Mettre à jour O: promoted=true, promoted_to=<layer>:<id>, crystallized_via=<signal>.
  9. Générer le proposal correspondant dans /proposed/.
```

**Proposal generation** : le synthesizer transforme une crystallisation en suggestion concrète selon sa cible :

- Pour une `preference` ou `instruction` → diff sur `CLAUDE.md` (en mode "ajout de section" ou "modification ciblée")
- Pour un `domain_fact` stable → entrée pour le système de mémoire
- Pour un `anti_pattern` → contre-instruction dans `CLAUDE.md`

### 5.6 Étage 6 — Briefing Render

**Rôle** : produire un rapport markdown digestible pour le user.

**Structure cible** (1-3 pages) :

```markdown
# Briefing — 2026-05-03 (run #14)

## TL;DR
- N sessions analysées (X depuis le dernier run)
- M nouveaux events captés
- K crystallisations
- J propositions de modification de CLAUDE.md

## Crystallisations cette run
[liste avec lien vers preuves]

## Propositions à valider
[diff CLAUDE.md proposé, side-by-side]

## Patterns émergents (pas encore crystallisés)
[ce qui est proche d'un seuil mais pas encore]

## Stale (à trancher)
[ce qui traîne en staging > 30 jours]
```

---

<a id="6"></a>
## 6. Schémas et structures de fichiers

### 6.1 Arborescence complète de `claude-meta/`

```
claude-meta/
├── README.md                          # Manifest + briefing résumé (~300 tokens)
├── logic/                             # Crystallisé seulement
│   ├── preferences.md                 # Préférences user (style, ton, format, longueur)
│   ├── domain_facts.md                # Faits stables (stack, projet, langues, contexte)
│   ├── instructions.md                # À pousser dans CLAUDE.md
│   ├── anti_patterns.md               # Ce que Claude ne doit PAS faire
│   ├── glossary.md                    # Terminologie spécifique au user
│   └── claude_skills.md               # Forces/faiblesses de Claude pour ce user
├── trace/                             # Routing direct
│   ├── sessions_dag.yaml              # DAG des projets/threads cross-session
│   ├── optimizer_reasoning_log.yaml   # Auto-continuité du skill
│   └── sessions/
│       ├── session_index.yaml         # Master index
│       ├── 2026-04-15_001.yaml        # Une entrée par session JSON
│       └── 2026-04-22_002.yaml
├── evidence/                          # Preuves brutes
│   ├── README.md
│   └── turn_excerpts.yaml             # Extraits exacts de turns référencés
├── staging/                           # Tampon de crystallisation
│   ├── observations.yaml
│   └── patterns.yaml
└── proposed/                          # Propositions à valider
    ├── claude_md_diff.md              # Diff prêt à appliquer
    ├── memory_candidates.yaml         # Pour le système de mémoire
    ├── preference_candidates.yaml     # Pour les préférences
    └── briefing.md                    # Rapport human-readable du dernier run
```

### 6.2 Schéma : `staging/observations.yaml`

```yaml
observations:
  - id: O0042
    timestamp: "2026-05-03T14:23"
    bound_to_session: "2026-05-02_007"
    bound_to_turns: [12, 13, 14]
    provenance: claude-inferred  # user-stated | user-corrected | user-affirmed | claude-inferred | pattern-derived
    content: "User prefers terse responses without preamble for technical questions"
    context: "Asked Claude for help debugging Python; responded with long preamble; user said 'skip the intro'"
    potential_type: preference  # preference | instruction | domain_fact | anti_pattern | claim
    target_layer: "logic/preferences.md"
    occurrences: [{session: "2026-05-02_007", turn: 13}]
    promoted: false
    promoted_to: null
    crystallized_via: null
    stale: false
```

### 6.3 Schéma : `logic/preferences.md`

```markdown
## P07: Terse responses for technical questions
- **Statement**: User prefers technical answers without preamble; skip "Great question!", skip "Let me help you with that", get to the substance.
- **Status**: stable | provisional | weakened
- **Provenance**: pattern-derived
- **Crystallized via**: recurrence-k (k=4)
- **Falsification**: would weaken if user requests preamble explicitly OR if user says "more context please" 3+ times.
- **Evidence**: 
  - 2026-04-15_001 turn 12 (user: "skip the intro")
  - 2026-04-22_002 turn 5 (user: "trop long, va à l'essentiel")
  - 2026-04-29_005 turn 8 (user: "directement le code stp")
  - 2026-05-02_007 turn 13 (user: "skip the intro")
- **From staging**: O0042
- **Proposed CLAUDE.md addition**: "For technical questions, omit preamble. Lead with the answer."
- **Tags**: style, response-length, technical
```

### 6.4 Schéma : `trace/sessions/2026-05-02_007.yaml`

Très proche du format ARA avec adaptations :

```yaml
session:
  id: "2026-05-02_007"
  source_file: "/path/to/exported_session.json"
  source_hash: "sha256:abc123..."
  date: "2026-05-02"
  turn_count: 18
  topic_summary: "Debugging Python asyncio race condition"
  ingested_at: "2026-05-03T14:20"
  ingested_by_run: 14

events_captured:
  - turn: 5
    type: friction
    id: F012
    routing: direct
    provenance: user-corrected
    summary: "User rejected asyncio approach, asked for sync"
  - turn: 13
    type: observation
    id: O042
    routing: staged
    provenance: claude-inferred
    summary: "User prefers terse style"

claude_actions:
  - turn: 4
    action: "Generated asyncio-based solution"
    files_changed: []
  - turn: 6
    action: "Pivoted to sync solution per user feedback"

dead_ends_logged:
  - turn: 4-5
    hypothesis: "asyncio-based debouncing"
    failure_mode: "user wanted sync; project context disallows async"
    lesson: "For this user, default to sync unless they request async"

key_excerpts:
  - turn: 13
    speaker: user
    excerpt: "skip the intro, just give me the code"

open_threads:
  - "Need to verify the sync solution works on Windows"

claude_inferences_pending:
  - "Possibly user dislikes preamble in general (O042)"
```

### 6.5 Schéma : `proposed/claude_md_diff.md`

Format diff lisible :

```markdown
# Proposed changes to CLAUDE.md (run #14)

## Add to Section "Response Style"

+ For technical questions, omit preamble — lead with the answer.
+ Default to sync code unless asked otherwise.

## Add new Section "Domain Context"

+ User works primarily in Python with a focus on data pipelines.
+ Project "OrionData" uses Postgres + dbt. References to "the warehouse"
+ mean the staging schema in OrionData unless context suggests otherwise.

## Remove from Section "Examples" (no longer accurate)

- (none this run)
```

Chaque proposition est *attachée* à une crystallisation, ce qui permet au user de cliquer/ouvrir l'evidence chain à la validation.

---

<a id="7"></a>
## 7. Closure signals adaptés aux sessions Claude

C'est le cœur épistémique du skill. ARA en a quatre ; je propose quatre adaptés à notre cas, plus un cinquième optionnel.

### 7.1 Recurrence-k (l'équivalent du *topic abandonment* inversé)

**Définition** : la même observation apparaît dans k sessions distinctes (k=3 par défaut, configurable).

**Pourquoi k=3** : c'est le seuil minimum pour distinguer un pattern d'une coïncidence. Avec k=2 on aurait beaucoup de faux positifs (deux fois la même request, mais avec un contexte différent). Avec k=4+ on serait trop conservateur et le skill prendrait des mois à apprendre quoi que ce soit.

**Garde-fou** : les k occurrences doivent être dans des **sessions différentes** (pas k turns dans la même session) ET sur des **topics différents** ou **contextes différents** (pour éviter de baker un truc qui était propre à un projet précis).

### 7.2 Verbal affirmation

**Définition** : dans une session, le user a explicitement validé l'observation par un énoncé first-person.

Exemples qui qualifient :
- "oui, à partir de maintenant fais toujours X"
- "exactement comme ça, retiens-le"
- "parfait, c'est ce que je veux"
- "c'est ma préférence générale"

Exemples qui NE qualifient PAS :
- "ok merci" (ack, pas affirmation)
- "ça marche" (acceptation contextuelle, pas préférence)
- silence (jamais une affirmation)
- "peut-être" (ambigu)

**Effet** : la provenance bascule de `claude-inferred` à `user-affirmed`. C'est le seul signal qui upgrade la provenance vers le tier *user-confirmé*.

### 7.3 Correction stable

**Définition** : le user a corrigé Claude sur le même travers k≥3 fois (cross-session).

C'est différent de recurrence-k parce que ça nécessite une *correction* (signal négatif), pas juste une mention. Exemple : 3 sessions où le user dit "non, pas asyncio".

**Effet** : crystallise en `anti_pattern` (pas en `preference`). La distinction est importante : un anti-pattern est une *contre-instruction* dans CLAUDE.md, pas une instruction positive.

### 7.4 Preference revealed

**Définition** : quand Claude a proposé plusieurs options, le user a systématiquement choisi la même k≥3 fois.

C'est le plus subtil et le plus puissant : c'est de la **préférence révélée**, pas déclarée. Exemple : Claude propose "version courte ou détaillée ?" et le user choisit court 4/4.

**Effet** : crystallise en `preference` avec provenance `pattern-derived`. Cette préférence est marquée comme révélée, ce qui permet au user de la distinguer d'une préférence qu'il aurait stated explicitement.

### 7.5 (Optionnel) — Long-stable presence

**Définition** : une observation reste en staging > N=30 jours sans être contredite ni renforcée.

**Effet** : flag `stale: true`. Le skill ne crystallise PAS automatiquement, mais surface l'observation au user dans le briefing pour qu'il tranche : valide ou rejette.

C'est l'équivalent du *stale-flagging* dans ARA. Crucial pour éviter qu'un staging gonfle indéfiniment.

### 7.6 Décharge automatique

Symétriquement aux closure signals, on a des **decay signals** qui *invalident* une crystallisation :

- Le user contredit explicitement la préférence → la crystallisation passe en `weakened`
- Le user demande explicitement le contraire pour la 2e fois → `weakened` → `refuted`
- Une observation `pattern-derived` n'a plus d'occurrences depuis N=60 jours → `weakened`

**Important** : on ne *supprime* jamais une entrée crystallisée. On la marque `weakened` ou `refuted`, et on laisse la trace. Pareil qu'ARA avec ses dead-end nodes : la trace est elle-même de la valeur.

---

<a id="8"></a>
## 8. Workflow d'utilisation et boucles de feedback

### 8.1 Setup initial (one-time)

```
1. Installer le skill: cp -r session-optimizer ~/.claude/skills/
2. Initialiser claude-meta/ dans le repo de travail (ou dans ~/claude-meta/ pour mode global)
3. (Optionnel) Configurer un cron / scheduled task pour /session-optimizer 1×/jour
```

### 8.2 Cycle de vie typique

```
[Tu as une session avec Claude.ai ou Claude Code]
[La session se termine, le JSON est exporté/persisté]
                ▼
[Plus tard, tu invoques /session-optimizer (ou cron déclenche)]
                ▼
[Le skill ingère les nouvelles sessions, traite, génère briefing.md]
                ▼
[Tu lis briefing.md — ~5 minutes de lecture]
                ▼
[Tu valides ou rejettes les propositions dans /proposed/]
                ▼
[Le skill applique les modifications validées vers CLAUDE.md / mémoires]
                ▼
[Les sessions suivantes bénéficient des updates]
                ▼
[Boucle se referme]
```

### 8.3 Modes de validation

Trois niveaux de granularité que je recommande de supporter :

- **`/session-optimizer review`** : ouvre `briefing.md` + `proposed/` pour validation manuelle item par item
- **`/session-optimizer apply --confirm`** : applique tout d'un coup avec une confirmation finale
- **`/session-optimizer apply --auto`** : applique sans demander (à réserver aux propositions très haute confiance)

### 8.4 Rollback

Toutes les modifications de CLAUDE.md passent par git (le skill `git commit` après chaque apply avec un message du type `claude-meta: apply run #14 - 3 props`). Rollback = `git revert`.

### 8.5 Boucle de feedback long terme

Le `optimizer_reasoning_log.yaml` permet au skill de se *self-monitor*. Si une crystallisation est `refuted` 2 runs après son introduction, c'est un signal que le skill a fait une erreur. Sur le long terme, ces signaux peuvent être agrégés pour calibrer les seuils (k=3 trop bas ? trop haut ?).

---

<a id="9"></a>
## 9. Considérations critiques et garde-fous

### 9.1 Risque #1 — Crystallisation prématurée

C'est le risque numéro 1, identifié dès le papier ARA. Solution : être **conservateur par défaut**. Mieux vaut un staging qui s'allonge qu'une crystallisation injustifiée. Les seuils par défaut (k=3) sont déjà conservateurs.

### 9.2 Risque #2 — Confusion provenance user vs inférée

Si CLAUDE.md se met à contenir des règles inférées sans que le user le sache, c'est une catastrophe d'UX. Garde-fou : **chaque entrée dans `claude_md_diff.md` indique sa provenance**. Le user voit tout de suite "ceci est inféré, pas dit par toi" et peut juger.

### 9.3 Risque #3 — Drift inter-projets

Si tu travailles sur 5 projets différents, une préférence captée sur le projet A ne s'applique pas forcément au projet B. Garde-fou : **scoping des observations**. Chaque crystallisation porte un champ `scope: global | project:X | language:Y`. CLAUDE.md de projet ne reçoit que les entrées scope `global` ou `project:<ce projet>`.

### 9.4 Risque #4 — Privacy / leak

Les sessions JSON peuvent contenir des secrets, des données personnelles, du code propriétaire. Garde-fous :
- Le skill ne sort *jamais* de la machine local (ou du repo)
- Les `evidence/turn_excerpts.yaml` peuvent être configurés pour ne stocker que des hashes au lieu d'extraits bruts (mode privacy strict)
- Une option `--redact` qui passe les évidences via un filtre (regex pour clés API, emails, etc.) avant stockage

### 9.5 Risque #5 — Rebuilding too fast

Si le skill tourne 1×/jour et propose 10 changements/jour, CLAUDE.md devient ingérable. Garde-fou : **rate limiting des propositions**. Pas plus de N=5 nouvelles propositions par run. Les autres restent en staging et passent au run suivant.

### 9.6 Risque #6 — Contradictions

Deux sessions disent des choses opposées. ARA le gère avec le *contradiction trigger* : flagger les deux entrées et générer un node `unresolved`. On garde la même mécanique, surface au user dans le briefing comme "à trancher".

### 9.7 Risque #7 — Le skill n'est pas déterministe

Comme tout LLM-driven pipeline, deux runs sur les mêmes inputs ne donneront pas exactement le même output. Atténuations :
- Logs détaillés des décisions (`optimizer_reasoning_log.yaml`)
- Idempotence visée pour les events factuels (un dead_end identifié sur turn 4-5 doit toujours être identifié pareil)
- Tolérance pour les jugements interprétatifs

### 9.8 Anti-pattern à éviter absolument : la flatterie en CLAUDE.md

L'analyse pourrait conclure "le user aime quand Claude est flatteur" parce que le user n'a jamais corrigé. C'est un faux positif : silence ≠ approbation. Garde-fou : **les preferences positives ne se crystallisent que sur affirmation explicite ou preference-revealed (choix actif)**, pas sur *absence de correction*.

---

<a id="10"></a>
## 10. Plan d'implémentation par phases

### Phase 1 — MVP mono-session (1-2 semaines de travail)

Objectif : valider la mécanique sur une seule session.

- Skill capable d'ingérer un JSON, parser, classifier
- Output minimal : `briefing.md` + `staging/observations.yaml`
- Pas de crystallisation encore
- Pas de proposed/

Critère de succès : sur 5 sessions test, est-ce que le skill identifie correctement les frictions/préférences/corrections ? Évaluation manuelle.

### Phase 2 — Multi-session + crystallisation (2-3 semaines)

Objectif : pipeline complet avec closure signals.

- Pattern Detector ajouté
- Maturity Tracker fonctionnel avec les 4 signaux
- Génération de `proposed/claude_md_diff.md`
- Validation manuelle des propositions

Critère de succès : sur un corpus de 20 sessions historiques, le skill produit-il des propositions pertinentes ? Le user les valide-t-il à >70% ?

### Phase 3 — Auto-apply + boucle long terme (2-3 semaines)

Objectif : closing the loop.

- Apply mode (semi-auto, full-auto)
- Decay signals
- Rollback via git
- Stale management

Critère de succès : utilisé sur 1 mois, est-ce que CLAUDE.md s'enrichit sans devenir ingérable ?

### Phase 4 — Optimisations (continu)

- Tuning des seuils (k=3 ? k=4 ?)
- Description optimization du skill (cf skill-creator)
- Évals quantitatifs : skill running on N test sessions, mesure precision/recall des extractions
- Cross-user patterns (mode partagé entre plusieurs users)

---

<a id="11"></a>
## 11. Annexes : exemples concrets

### Annexe A — Walk-through complet sur une session imaginaire

**Session JSON (résumé)** :

```
Turn 1 - User: "Aide-moi à débugger un bug Python"
Turn 2 - Claude: "Bien sûr ! Je serais ravi de vous aider. Pour mieux comprendre votre problème, pouvez-vous partager le code qui pose problème ainsi qu'un exemple de l'erreur que vous obtenez ? Cela me permettra de..."
Turn 3 - User: "skip the preamble. voici le code: [code]"
Turn 4 - Claude: "Je propose une approche async avec asyncio..."
Turn 5 - User: "non sync stp, le projet est sync"
Turn 6 - Claude: [pivot vers solution sync]
Turn 7 - User: "parfait, exactement"
[...]
Turn 18 - User: "merci"
```

**Étage 1 — Discovery** : session_index ne contient pas cette session, elle est ingérée.

**Étage 2 — Context Harvester** : extrait :
```
- turn 3: user reformulation negative + prescriptive ("skip the preamble")
- turn 4-5: claude proposition + user correction (asyncio rejected)
- turn 6: claude pivot
- turn 7: user explicit affirmation ("parfait, exactement")
```

**Étage 3 — Event Router** : 
```
- E1 (direct, friction): turn 3, user-corrected, "preamble unwanted"
- E2 (direct, dead_end): turns 4-5, hypothesis "asyncio approach", failure_mode "user wanted sync, project is sync", lesson "default sync for this user"
- E3 (direct, pivot): turn 6, from "async" to "sync"
- O1 (staged, preference): "user prefers terse style without preamble", potential_type=preference, provenance=claude-inferred
- O2 (staged, domain_fact): "user's project is sync (no asyncio)", potential_type=domain_fact, provenance=user-stated
```

**Étage 4 — Pattern Detector** : 
- Cherche dans les sessions précédentes des patterns liés à "preamble" et "sync vs async"
- Trouve 2 occurrences précédentes de friction sur le préambule
- Total : 3 occurrences → declenche recurrence-k pour O1

**Étage 5 — Maturity Tracker** :
- O1 (preference, terse) : signal `recurrence-k` ✓ → crystallisé en `logic/preferences.md:P07`
- O2 (domain_fact, project sync) : provenance déjà user-stated mais peut-on être sûr que c'est toujours vrai pour CE projet ? On stage encore.

**Étage 6 — Briefing** :
```markdown
# Briefing 2026-05-03 (run #14)

## TL;DR
- 1 session ingérée
- 4 events captured (1 friction, 1 dead_end, 1 pivot, 2 obs)
- 1 crystallisation (P07: terse style, via recurrence-k)
- 1 proposition CLAUDE.md

## Crystallisations
### P07 — Terse style without preamble
- Provenance: pattern-derived (k=3 occurrences cross-session)
- Evidence: sessions 2026-04-15, 2026-04-22, 2026-05-02
- Proposed CLAUDE.md addition: "For technical questions, omit preamble — lead with the answer."

## Patterns émergents
- Possible "default sync for Python projects" — needs 1 more occurrence

## Stale: none
```

**Validation user** : tu lis, tu approuves P07, le skill applique le diff dans CLAUDE.md, commit git.

**Session suivante** : Claude charge CLAUDE.md → lit "omit preamble" → comportement aligné dès le turn 1.

### Annexe B — Le SKILL.md complet

(Voir fichier séparé `session-optimizer/SKILL.md`)

### Annexe C — Templates pour les artefacts produits

(Voir dossier séparé `session-optimizer/templates/`)

---

## Conclusion

ARA n'est pas un protocole de recherche scientifique en surface, c'est un **protocole de capture épistémique** dont la mécanique (provenance, staging, closure-driven crystallization, forensic bindings) résout un problème universel : *comment accumuler de la connaissance fiable à partir d'observations bruitées sans crystalliser prématurément du faux*.

Les sessions Claude sont littéralement le même problème, déguisé. Le skill `session-optimizer` est l'instanciation de ce protocole sur ce nouveau substrat. Les bénéfices attendus sont massifs : élimination des frictions récurrentes, préférences révélées capturées, dead-ends mémorisés. À terme, chaque session fait de Claude un meilleur partenaire pour la suivante, sans effort de documentation.

Le travail à faire est principalement dans le tuning et la validation empirique. La méthodologie, elle, est solide — elle a été testée sur PaperBench et RE-Bench, deux benchmarks scientifiques exigeants.

**Mon avis** : tu as raison sur l'ampleur. Cette méthodologie est énorme. Le pari est qu'elle marche aussi bien hors recherche scientifique. Tout indique que oui, mais ça vaut un MVP soigné.
