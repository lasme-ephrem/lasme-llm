# Rapport final — Tranche 2 du produit (2026-09-19)

Suite des phases 0-5 (voir `RAPPORT_PHASE{2..5}.md`) : cette tranche
transforme la plateforme refondée en **produit final utilisable**.

## Livré, étape par étape

| # | Étape | Preuve |
| --- | --- | --- |
| T1 | Consolidation Git : `main` poussé (PR #9 réconciliée — version antérieure du même travail, fusion `ours`, arbre vérifié identique) | push `0273ac8..1473398`, 152 tests verts sur main |
| T2 | **Persistance des missions** : table `agent_runs` (événements JSON, usage), `GET/DELETE /api/agent/runs`, sauvegarde automatique ; console avec panneau « Missions » et **replay complet de timeline** | 5 tests ; GUI : mission artefact rejouée (bulle, carte outil, finale) |
| T3 | **Vision dans la console** : bouton 📎, vignette, retrait ; image pré-liée au run (le modèle n'a plus qu'à questionner via `analyze_image`) | live : carré rouge + cercle bleu décrits exactement par le 12B |
| T4 | **Canvas outillé** : `artifact_create` / `artifact_update` / `artifacts_list` sur l'ArtifactStore versionné | live : « Cheatsheet Python » créé par l'agent, retrouvé via `/api/artifacts` |
| T5 | **Contexte projet** : `project_id` accepté, instructions du projet injectées dans le prompt système de la boucle | code + tests (mémoire de projet dans la boucle) |
| T6 | **Pattern routers** : domaine agent extrait de `main.py` vers `routers/agent.py` (fabrique + dépendances injectées, zéro changement de comportement) | 160 tests verts, chemins API identiques |
| T7 | **CI locale** : `scripts/validate_all.py` — statique (compileall, node ×4, pytest, pip check) + `--live` (évals, budgets perf). Batterie d'évals portée à **8 scénarios** dont 2 adversariaux | statique 7/7, live **10/10** ; évals **8/8 (100 %)** ; 12B 209 tok/s, E4B 145 tok/s |
| T8 | Validation GUI finale (historique, replay, contrastes corrigés et re-vérifiés visuellement), README enrichi | captures analysées : tous éléments présents et lisibles |

## État du produit livré

- **Runtime** : llama.cpp router (12B 128K / E4B / E2B / 12B-256K), MTP,
  prompt caching, superviseur `scripts.serve`, sans Ollama.
- **Agent** : orchestrateur borné (tours, budget, boucle), 12 outils
  (calculate, current_time, echo, web_search, fetch_pages, rag_search,
  python_run, files_list, files_read_text, analyze_image,
  artifact_create, artifact_update, artifacts_list), missions
  persistées et rejouables, contexte projet, vision jointe.
- **Interfaces** : chat v1 complet (projets, fichiers, RAG, canvas,
  exports) + console agent `/agent.html` (timeline, historique, image).
- **Qualité** : 160 tests verts, évals 8/8, budgets perf verts,
  `validate_all` en une commande.

## Démarrage

```powershell
powershell -File scripts\start_local.ps1   # router + app + dépendances
# http://127.0.0.1:8000/           → chat
# http://127.0.0.1:8000/agent.html → console agent
```

## Suite possible (non bloquant)

Poursuite du découpage `main.py` domaine par domaine sur le pattern T6 ;
migration du chat v1 vers la timeline agent unifiée ; provider
tinyfish/Monid en `search_fn` si besoin ; évals élargies (web sourcé,
RAG) dans `validate_all --live`.
