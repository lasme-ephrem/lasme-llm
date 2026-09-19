# Rapport Phase 5 — qualité, évals et durabilité (2026-09-19)

## Livré

- **`scripts/eval_agents.py`** — batterie d'évals agentiques rejouable
  contre le runtime vivant : 6 scénarios (calcul direct, puissance, somme
  de Gauss, heure, sans-outil, multi-outils), scoring automatique
  (succès de tâche, appels d'outils, malformations, tours, durée),
  sortie JSON + seuil d'échec (`--min-success`, défaut 80 %).
- **`scripts/check_perf.py`** — budget de régression performance :
  mesure la médiane tok/s sur le router et échoue sous −10 % de la
  baseline Phase 0 ; baselines versionnées dans
  `.models/logs/perf_baseline.json` (`--update-baseline`).
- **Documentation v2** : README refondu (profils Gemma 4 mesurés,
  architecture router, installation sans Ollama, commandes de
  validation v2), `.env.example` complet (variables `LLAMA_*`),
  rapports de phase 2-5.

## Preuves

- **Évals agentiques (runtime vivant)** :
  - `gemma-4-e4b` : **6/6 (100 %)**, 0 appel malformé, 0,7-1,7 s par
    mission, 1-2 tours ;
  - `gemma-4-12b` : **6/6 (100 %)**, 0 appel malformé, 0,8-2,3 s ;
  - y compris la somme de Gauss (5050) via expression arithmétique et
    le scénario multi-outils (calculate + current_time en 2 appels).
- **Budget performance** : 12B 190,4 tok/s ≥ plancher 189,9 ;
  E4B 135,8 ≥ 116,1 → **PASS** (légère contention mesurée quand les
  deux profils co-résident, documentée).
- **Suite de tests** : 152 verts (2,4 s) — barre portée de 111 à 152
  depuis le début de la refonte, zéro test supprimé.

## Bilan de la refonte (Phases 0-5)

| Phase | Livraison | Preuve clé |
| --- | --- | --- |
| 0 | Benchmark complet, profils verrouillés | 211 tok/s, 256K tient, cache ×42 |
| 1 | Runtime llama.cpp v2 (router, superviseur) | chat v1 100 % sur llama-server |
| 2 | Cœur agentique (orchestrateur, outils) | run live 3 tours, 0 malformage |
| 3 | Suite d'outils (web/récence, RAG, sandbox) | 385 exact en Docker, web sourcé |
| 4 | Console agent (module ES, timeline) | GUI testé navigateur : 406 exact |
| 5 | Évals + budget perf + docs | 12/12 scénarios, perf PASS |

Commits : `dc84c6f` → `cb5d9e6` → `dd99753` → `ddd44b8` → `2691308` →
`ec7a81d` → `dd541d8` (+ présent commit).

## Reste connu (tranche 2, assumé)

- Éclatement de `chat/server/main.py` en routers — à faire avec la
  migration du chat v1 vers la timeline agent.
- Canvas/artefacts pas encore exposés comme outils agent.
- tinyfish/Monid : provider injectable prévu (`search_fn`) mais non
  câblé (API gateway payante à l'usage ; la chaîne gratuite DDG +
  spécialistes couvre l'usage actuel).
- `analyze_image` validé unitairement, pas encore en démo live.
