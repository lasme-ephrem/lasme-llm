# Rapport final — Plateforme agentique unifiée (2026-09-19)

Dernière ligne droite de la refonte : **le chat principal `/` est devenu
le produit agentique**. La console `/agent.html` reste comme banc de
test, mais tout vit désormais dans l'interface de conversation.

## Ce qui change pour l'utilisateur

- Chaque message du chat passe par **la boucle agentique** : le modèle
  peut raisonner, appeler les 13 outils (calcul exact, Python sandboxé
  Docker, recherche web sourcée, lecture de documents RAG, création
  d'artefacts Canvas, fichiers, vision, date/heure), puis répondre.
- **Les appels d'outils s'affichent dans le fil** : carte repliable
  verte (ou rouge en cas d'échec) avec arguments et résultat, durée ;
  le raisonnement apparaît compacté (« Analyse terminée · X s »).
- La **recherche web automatique** du chat v1 reste active et se
  combine aux outils (citations web + outils dans la même réponse).
- **Identité v2 partout** : sélecteur à 4 profils Gemma 4 (12B / E4B /
  E2B / 12B-256K), défaut migré en base (`gemma-4-12b`), icônes et
  libellés de performance par profil ; plus aucune mention Muse
  Glimmer.
- Sessions, branchement, modification, régénération, Canvas, mémoire,
  projets : tout le socle v1 est conservé et désormais actionnable
  par l'agent.

## Preuves (live, navigateur réel)

1. « Combien font (17*23)+100 ? » → carte `calculate — < 5 ms`,
   réponse **491** rendue en LaTeX, **320 tok/s**, suggestions.
2. « Exécute dans le bac à sable Python la somme des carrés des 8
   premiers entiers » → carte `python_run — 4142 ms` (Docker réel),
   raisonnement compacté 11,2 s, web-auto « 3 sources pertinentes »,
   réponse **204** exacte, 5 400 tok/s de prompt.
3. Console panneau Canvas montrant l'artefact créé précédemment par
   l'agent (« Cheatsheet Python · v1 »).
4. `validate_all --live` : **10/10** (compileall, node ×4, pytest 162,
   pip check, évals agent **8/8 (100 %)**, budgets perf **211,5** et
   **151,5 tok/s** ≥ planchers).

## Chaîne technique

`POST /api/chat/stream` construit le contexte v1 (mémoire, compaction,
RAG, web-auto, instructions projet) puis délègue à l'orchestrateur
(`core/agent`), dont les événements sont convertis en SSE : contrat
historique conservé (`reasoning_start/done`, `content_delta`,
`generation_stats`) + `agent_tool_call` / `agent_tool_result`. Le
message assistant persiste avec `metadata.agent` (run_id, tours,
outils) — les runs restent consultables via `/api/agent/runs`.

## État des phases

| Phase | Contenu | État |
| --- | --- | --- |
| A | Backend : chat sur orchestrateur | ✅ commit `8000dcd`, 2 tests d'intégration |
| B | Frontend : cartes d'outils dans le fil | ✅ commit `bd2c212`, preuve GUI |
| C | Identité modèle v2 + migration défaut | ✅ commit `a2718ae` |
| D | Extraction routers supplémentaires | reporté (pattern posé, mécanique) |
| E | Validation complète + merge + push | ✅ ce commit |

## Suite (optionnelle, non bloquante)

Extraction des routers restants sur le pattern `routers/agent.py`,
retrait éventuel de la console `/agent.html`, évals conversationnelles
supplémentaires dans `validate_all`, GIF de démo à jour.
