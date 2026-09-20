# Lasme LLM

Plateforme de chat IA **locale et agentique**. Une seule interface
(<http://127.0.0.1:8000>) sert à la fois de chat et d'agent : chaque message
passe par une boucle d'orchestrateur qui raisonne, appelle des outils (recherche
web, Python sandboxé, documents, images…), puis répond avec des citations
vérifiables. L'inférence tourne intégralement sur votre machine via llama.cpp,
sur une RTX 4070 Ti SUPER 16 Go.

<p align="center">
  <img
    src="docs/assets/lasme-llm-demo.gif"
    alt="Démonstration de Lasme LLM"
    width="960"
  >
</p>

## Pourquoi ce projet

- **Local et souverain** : modèle, conversations, fichiers et index
  documentaire restent sur votre disque ; la recherche web est optionnelle —
  sans clé API, la chaîne gratuite (DuckDuckGo, GDELT, OpenAlex, Wikimedia)
  fonctionne déjà.
- **Agentique** : pas de « mode agent » séparé. Le chat est l'agent : chaque
  message traverse une boucle d'orchestrateur déterministe autour du modèle.
- **Rapide** : speculative decoding MTP et router multi-modèles llama.cpp —
  129 à 214 tok/s mesurés selon le profil.

## Fonctionnalités

**Boucle d'agent**, avec garanties du harnais :

- raisonnement → appels d'outils → réponse, en 6 tours maximum par message ;
- budget de tokens par appel modèle (2 048 au départ, doublé une fois
  jusqu'à 12 288 si la réponse est tronquée) ;
- détection de boucle : un appel d'outil identique répété 3 fois est refusé ;
- après un `web_search`, lire au moins une page est obligatoire : si le
  modèle répond depuis les extraits, l'orchestrateur récupère lui-même les
  URLs pertinentes et les injecte dans le contexte ; si la demande exige une
  recherche, répondre de mémoire est retoqué une fois.

**Recherche web agentique** :

- chaîne de fournisseurs de liens : Monid (tinyfish, si `MONID_API_KEY`) en
  source prioritaire — gratuit via tinyfish, sync/async, cache d'endpoint
  24 h, garde-fou `MONID_MAX_PRICE_USD` — puis spécialistes (GDELT, OpenAlex,
  Wikimedia), Brave, Tavily et DuckDuckGo en repli automatique ;
- aucun fournisseur synthétique (Sonar/Perplexity) n'est appelé par l'agent :
  le modèle reçoit des liens bruts numérotés et lit les pages lui-même via
  `fetch_pages` ;
- portail d'actualité : les questions sensibles au temps (superlatifs
  temporels, données vivantes, années ≥ 2024) forcent la recherche web —
  la page lue prime sur la mémoire d'entraînement ;
- les citations vers des URLs jamais consultées sont retirées de la réponse.

**Citations et lecture** :

- citations par marqueurs `[n]` (numérotation cumulée par message), résolues
  côté interface en puces favicon cliquables à l'endroit exact de la citation
  — carte au survol (favicon, domaine, titre, pagination), tap mobile,
  fermeture par `Échap`, proxy favicons local `/favicons/{domain}` ;
- panneau de Réflexion : raisonnement streamé dans un panneau dédié
  (mi-hauteur, auto-scroll), replié à la fin du calcul et ré-ouvrable au
  clic, isolé du texte de la réponse ;
- deux efforts de raisonnement : **Approfondi** (défaut) et **Maximum**.

**Outils de l'agent** (schémas JSON stricts, sortie bornée) :
`web_search`, `fetch_pages`, `python_run` (pool Docker chaud), `calculate`,
`analyze_image` (vision Gemma 4 native), `artifact_create`/`artifact_update`/
`artifacts_list`, `rag_search`, `files_list`, `files_read_text`,
`current_time`.

**Mémoire et projets** : conversations persistées en SQLite avec compaction
du contexte ; projets isolant instructions, fichiers, artefacts et mémoire ;
RAG sur documents (PDF, Office, Markdown, images) avec classement hybride
lexical + vectoriel local et citations fichier/page.

**Statistiques honnêtes** : le tok/s affiché agrège les temps de décodage
réellement mesurés par tour de modèle (hors exécution des outils), avec TTFT
et durée mur.

## Architecture

```
Navigateur — chat/web (interface unique, http://127.0.0.1:8000)
     │  SSE : reasoning_delta · content_delta · agent_tool_call/result · generation_stats
     ▼
FastAPI — chat/server/main.py
     │
     ├─► Orchestrateur agentique — core/agent/
     │     boucle THINK → outils → FINAL, budget, anti-boucle, nudges
     │
     ├─► Runtime llama.cpp — core/inference/ : superviseur du llama-server
     │     en mode router (--models-preset), profils Gemma 4 QAT, MTP,
     │     KV quantifié, client OpenAI-compatible
     │
     ├─► Outils plateforme — core/runner/ (Python Docker), core/rag/,
     │     core/files/, core/artifacts/, core/memory/
     │
     └─► Recherche web — core/tools/ : Monid (tinyfish) → GDELT ·
           OpenAlex · Wikimedia → Brave → Tavily → DuckDuckGo (repli sans clé)
```

## Prérequis

- **Python ≥ 3.11**
- **llama.cpp compilé avec CUDA** : le superviseur cherche `llama-server.exe`
  dans `~/llama.cpp/build/bin/Release/`, puis dans le `PATH`
  (chemin personnalisable via `LLAMA_SERVER_PATH`)
- **Docker Desktop** (optionnel) : uniquement pour le runner Python isolé
- **Clés API optionnelles** : Monid, Brave, Tavily, OpenAlex — sans clé, la
  recherche web repose sur les fournisseurs gratuits

## Installation

```powershell
git clone https://github.com/lasme-ephrem/lasme-llm.git
cd lasme-llm
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Renseigner dans `.env` uniquement les fournisseurs souhaités. Les modèles
Gemma 4 QAT (`unsloth/gemma-4-*-it-qat-GGUF`, drafter MTP et projection
vision inclus) sont téléchargés automatiquement depuis Hugging Face au
premier démarrage du router. Pour le runner Python, construire l'image une
fois (`scripts/start_local.ps1` le fait automatiquement) :

```powershell
docker build -t lasme-python-runner:latest .\infra\runner
```

## Configuration

Toutes les variables se lisent dans `core/config.py` (et `.env.example`) :

```text
# Runtime llama.cpp
LLAMA_SERVER_PATH=            # vide = découverte auto (~/llama.cpp puis PATH)
LLAMA_BASE_URL=http://127.0.0.1:8080   # (= LLAMA_HOST:LLAMA_PORT)
LLAMA_HOST=127.0.0.1
LLAMA_PORT=8080
LLAMA_MODELS_MAX=2            # modèles chargés simultanément par le router
LLAMA_STARTUP_TIMEOUT=120

# Modèles = profils du router (gemma-4-12b / e4b / e2b / 12b-256k) ;
# les alias Ollama historiques restent acceptés et routés sur ces profils
CHAT_MODEL=gemma-4-12b
FAST_MODEL=gemma-4-e4b
REASONING_MODEL=gemma-4-12b
CODING_MODEL=gemma-4-12b
VISION_MODEL=gemma-4-12b
# Recherche web (toutes optionnelles)
MONID_API_KEY=                # source prioritaire (tinyfish via api.monid.ai)
MONID_MAX_PRICE_USD=0.01      # refus des endpoints Monid au-delà de ce prix
MONID_TIMEOUT_S=30
BRAVE_SEARCH_API_KEY=
TAVILY_API_KEY=
OPENALEX_API_KEY=             # clé gratuite (openalex.org)
SEARCH_SPECIALISTS_ENABLED=true
PERPLEXITY_API_KEY=           # ignoré par l'agent (fournisseurs de liens only)

# Sécurité / accès distant
LASME_ACCESS_TOKEN=           # exigé pour toute API passant par un proxy
LASME_ALLOW_REMOTE_CODING=false
LASME_ALLOW_DESTRUCTIVE_AGENT_TOOLS=false
LASME_ENABLE_AGENT_TERMINAL=false
LASME_WORKSPACE_ROOT=         # confinement des outils de fichiers
LASME_MAX_UPLOAD_BYTES=26214400
LASME_ENABLE_EXTERNAL_IMAGE_GENERATION=true
# Runner Python
LASME_RUNNER_POOL=            # 0 = force un conteneur froid par tâche
LASME_DOCKER_BINARY=          # si Docker Desktop est absent du PATH
```

S'exposent aussi : `LASME_ALLOWED_COMMANDS`, `LASME_PUBLIC_BASE_URL`,
`EXTRA_MODELS`, `HF_HOME`. `OLLAMA_BASE_URL` est un vestige de la v1 :
encore déclaré dans `core/config.py` mais sans effet, le client v2 parle à
`LLAMA_BASE_URL`.

## Démarrage

Le plus simple — démarre le router llama.cpp, construit l'image du runner si
besoin, lance l'API et attend le health check :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
```

Ou manuellement (le superviseur génère `.runtime/llama/router_models.ini`
puis lance llama-server, de façon idempotente) :

```powershell
.\.venv\Scripts\python.exe -m scripts.serve start
.\.venv\Scripts\python.exe -m uvicorn chat.server.main:app --host 127.0.0.1 --port 8000
```

soit, équivalent direct : `llama-server --models-preset
.runtime/llama/router_models.ini --models-max 2 --jinja --host 127.0.0.1
--port 8080`.

Arrêt : `python -m scripts.serve stop` (router) et `.\scripts\stop_local.ps1`
(API). Pilotage : `status`, `metrics --model <profil>`, `info`.
Ouvrir ensuite <http://127.0.0.1:8000/>.

## Modèles et performances

Quatre profils Gemma 4 QAT servis par un seul llama-server en mode router
(E4B et E2B préchargés, 12B chargé à la demande, `LLAMA_MODELS_MAX`
instances simultanées). Mesures Phase 0 sur RTX 4070 Ti SUPER 16 Go :

| Profil | Contexte | Rôle | Débit mesuré |
| --- | --- | --- | ---: |
| `gemma-4-12b` (défaut) | 128K | qualité/agent, vision native | 211 tok/s |
| `gemma-4-e4b` | 64K | rapide, résident | 129 tok/s |
| `gemma-4-e2b` | 32K | minimal, résident | 214 tok/s |
| `gemma-4-12b-256k` | 256K | très longs documents, KV q8_0 | 162 tok/s |

- **Speculative decoding MTP** (`draft-mtp`, n=4) sur tous les profils
  (×3,4 sur le 12B vs sans MTP) ; **KV cache quantifié** q8_0 sur le profil
  256K — le q4_0 est écarté (dégradation documentée du tool calling).
- Budgets de non-régression dans `.models/logs/perf_baseline.json`
  (193 tok/s 12B, 136 tok/s E4B, 214 tok/s E2B), appliqués par
  `scripts/check_perf`.

## Tests et validation

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
node --test tests\js\math-renderer.test.cjs tests\js\progressive-renderer.test.cjs

# Tout en une commande — statique + tests ; --live ajoute les évals agent
# et les budgets perf (router démarré requis) :
.\.venv\Scripts\python.exe -m scripts.validate_all [--live]

# Budgets de performance et évals agentiques ciblées :
.\.venv\Scripts\python.exe -m scripts.check_perf --model gemma-4-12b
.\.venv\Scripts\python.exe -m scripts.eval_agents --model gemma-4-e4b
```

## Sécurité

- clé API jamais journalisée ni commitée (redaction dans les logs, `.env`
  gitignoré) ;
- exécution Python durcie : conteneur Docker sans réseau, racine en lecture
  seule, utilisateur non privilégié, limites mémoire/CPU/processus/durée ;
  pool chaud (`docker exec`) avec balayage des processus errants ;
- arguments d'outils validés contre un sous-ensemble JSON strict
  (`core/agent/tools.py`) ;
- routes de codage et outils destructifs désactivés par défaut ; toute API
  reçue via un proxy exige `LASME_ACCESS_TOKEN`.

Détails : [docs/SECURITY.md](docs/SECURITY.md).

## Licence

Lasme LLM est distribué sous [Apache License 2.0](LICENSE). Voir
[NOTICE](NOTICE) pour les attributions des ressources navigateur redistribuées
(DOMPurify, highlight.js, KaTeX, marked, Mermaid) et la déclaration
d'implémentation indépendante.
