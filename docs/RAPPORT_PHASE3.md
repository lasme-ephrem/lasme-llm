# Rapport Phase 3 — suite d'outils v2 (2026-09-19)

## Livré

**Outils web** (`core/agent/tools_web.py`) — refonte inspirée de l'étude
tinyfish/Monid :
- `web_search(query, max_results, recency)` : fenêtre de fraîcheur
  **explicite** (jusqu'à la dernière heure), sortie compacte numérotée
  model-ready. Moteur par défaut = la chaîne v1 éprouvée
  (`search_web_detailed` : Sonar → spécialistes GDELT/OpenAlex/Wikimedia
  → SearXNG → Brave → Tavily → DDG, arrêt adaptatif, dédup, ranking) —
  **enveloppée, pas réécrite** ; un moteur alternatif (tinyfish via
  Monid discover/run) s'injecte par `search_fn` sans toucher au contrat.
- `fetch_pages(urls[1..5])` : récupération **par lots**, markdown
  model-ready, budget de caractères partagé, erreurs isolées par URL.

**Outils plateforme** (`core/agent/tools_platform.py`, DI complète) :
- `rag_search` : passages + citations `[Document : fichier, p. X]` via
  `search_scopes` du RAG hybride existant ;
- `python_run` : le runner Docker durci existant (sans réseau, UID
  dédié, limites) exposé comme outil — stdout/stderr/fichiers produits ;
- `files_list` / `files_read_text` : bibliothèque de fichiers projet ;
- `analyze_image` : vision native Gemma 4 (contenu OpenAI multi-part),
  activée quand un client vision est injecté.

**Composition** (`core/agent/registry.py`) : `build_agent_registry()`
assemble builtin + web + plateforme avec moteurs injectables ;
`/api/agent/stream` câblé avec les vraies dépendances (rag_store,
python_runner, project_file_store, client, chaîne web).

## Preuves

- **Tests** : 8 nouveaux (`tests/test_agent_tools_v2.py`) — récence
  appliquée et formatage, lots fetch avec erreurs isolées, citations
  RAG, rapport python_run, fichiers, absence de vision sans client,
  outils inconnus listés. Suite complète : **152 verts**.
- **Live (run réel)** :
  - `python_run` en vrai Docker : code Python valide généré par E4B,
    exécuté en bac à sable (exit 0, 3 375 ms), stdout 385, réponse
    finale « la somme des carrés des 10 premiers entiers est 385 » —
    **exact** ;
  - `web_search` sans aucune clé API : deux appels adaptatifs du modèle
    (requête affinée), fallback DuckDuckGo fonctionnel, réponse sourcée
    avec noms et URLs.

## Décisions notables

- La chaîne de recherche v1 est conservée comme moteur : ses 2 300
  lignes encodent des mois d'ajustements (verticaux, evidence,
  escalade) que réécrire aurait détruits. La valeur tinyfish (récence
  explicite, lots, markdown) est capturée dans le **contrat d'outil**.
- `analyze_image` construit lui-même le contenu multi-part OpenAI — le
  client v2 laisse passer les messages structurés tels quels.
- Les outils s'activent par présence de dépendance (pas de flag) : sans
  Docker, `python_run` n'existe pas et le modèle ne peut pas l'appeler.

## Porte de sortie

Atteinte : 8 outils au registre (calculate, current_time, echo,
web_search, fetch_pages, rag_search, python_run, files_list,
files_read_text, + analyze_image optionnel), tous testés, dont deux
validés en live bout-en-bout.
