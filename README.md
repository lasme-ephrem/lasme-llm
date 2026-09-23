# Lasme LLM

Plateforme de chat IA **locale et agentique**. Une seule interface
(<http://127.0.0.1:8000>) sert à la fois de chat et d'agent : chaque message
passe par une boucle d'orchestrateur qui raisonne, appelle des outils (recherche
web, Python sandboxé, documents, images…), puis répond avec des citations
vérifiables. L'inférence tourne intégralement en local via llama.cpp
(RTX 4070 Ti SUPER 16 Go).

<p align="center"><img src="docs/assets/lasme-llm-demo.gif" alt="Démonstration de Lasme LLM" width="960"></p>

## Pourquoi ce projet

- **Local et souverain** : modèle, conversations, fichiers et index
  documentaire restent sur votre disque. La recherche web est optionnelle
  et passe par des serveurs MCP (Exa, Brave, Tavily). La fraîcheur sport,
  météo, actu tech et Wikipédia vient d'un serveur MCP local.
- **Agentique** : pas de « mode agent » séparé — le chat est l'agent, chaque
  message traverse une boucle d'orchestrateur déterministe.
- **Rapide** : speculative decoding MTP, router multi-profils llama.cpp
  (129 à 214 tok/s mesurés), et un affichage qui ne retient pas le texte
  déjà produit.

## Fonctionnalités

**Boucle d'agent**, avec garanties du harnais : raisonnement → appels
d'outils → réponse, en 6 tours maximum ; budget de tokens par appel modèle
calé sur l'effort choisi, doublé une fois — plafonné à 12 288 — si la
réponse est tronquée ; un appel d'outil identique répété 3 fois est refusé ;
après un `web_research`, lire au moins une page (`web_read`) est obligatoire —
si le modèle répond depuis les extraits, l'orchestrateur récupère lui-même
les URLs pertinentes, et répondre de mémoire alors que la demande exige une
recherche est retoqué une fois.

**Effort de raisonnement** : sélecteur standard **Low / Medium / High**
(échelle `reasoning_effort`, passée telle quelle au modèle) sous forme de
slider segmenté — navigation clavier aux flèches, **défaut Medium** au
lancement. Budgets de réponse : Low 4 096 tokens, Medium 6 144, High le
budget complet du profil (8 192 sur le 12B).

**Recherche web** :

- MCP **Exa**, **Brave** et **Tavily** combinés ; sans clé, le serveur
  correspondant ne démarre pas ;
- fraîcheur sport, météo, actu tech et Wikipédia via le serveur MCP local ;
- autres MCP selon le modèle (e2b minimal, e4b intermédiaire, 12b complet) :
  Context7, GitHub, Git, filesystem sandbox, SQLite, graphiques AntV,
  fuseaux horaires ;
- l'agent appelle `web_research`, puis lit les pages avec `web_read` ;
  les citations d'URLs jamais consultées sont retirées ;
- portail d'actualité : les questions sensibles au temps (superlatifs
  temporels, données vivantes, années ≥ 2024) forcent la recherche —
  la page lue prime sur la mémoire d'entraînement.

**Interface** :

- **citations style ChatGPT** : les marqueurs `[n]` globaux (numérotation
  cumulative par message) deviennent des puces favicon à l'endroit exact de
  la citation — carte au survol (titre, domaine, pagination), tap mobile.
  Pas de section « Sources » : la preuve vit dans le texte ;
- **streaming multi-chats parallèle** : changer de conversation ou en créer
  une pendant qu'une autre génère n'interrompt jamais le flux — il continue
  en arrière-plan (points pulsants dans la sidebar) et la ré-entrée
  reconstruit le tour en cours à l'identique (Réflexion, cartes d'outils,
  étapes de recherche) puis rebranche le live ;
- **édition d'un message envoyé = même fil** : le message est mis à jour en
  place, la suite est tronquée et la réponse régénérée dans la même
  conversation (`POST /api/sessions/{id}/messages/{id}/edit`) ; créer une
  variante reste possible via le bouton Branche explicite ;
- **titres de conversations générés par le modèle** : produits en parallèle
  du premier flux, 3-6 mots dans la langue de l'utilisateur, première lettre
  majuscule, apostrophes françaises préservées (budget 512 + retry) ;
- **réflexion** : une ligne « Réflexion… », puis « A réfléchi pendant N s ».
  Le texte s'ouvre au clic, sans cadre. La réponse n'apparaît qu'une fois
  les outils et la réflexion terminés ;
- **outils** : un seul bloc, une ligne par appel, icônes dans le vert du
  thème ;
- **rendu mathématique complet** : KaTeX avec `$...$`, `$$...$$`, `\(...\)`
  et `\[...\]`, matrices `pmatrix` incluses — macros passées en copie
  mutable (l'objet gelé faisait échouer le rendu) et boucle auto-render
  jusqu'à stabilité ;
- **statistiques honnêtes** : tok/s = décodage réellement mesuré par tour
  de modèle (hors outils), avec TTFT et durée mur.

**Outils natifs** : `calculate`, `current_time`, `python_run` (pool Docker
chaud), RAG, fichiers projet, artefacts, `analyze_image` (vision Gemma 4).
La recherche est `web_research` / `web_read` (MCP). Les autres MCP suivent
le modèle, comme ci-dessus. **Mémoire et projets** : conversations persistées en
SQLite avec compaction du contexte ; projets isolant instructions, fichiers,
artefacts et mémoire ; RAG sur documents (PDF, Office, Markdown, images)
avec classement hybride lexical + vectoriel local et citations fichier/page.

## Architecture

```
Navigateur — chat/web (interface unique, http://127.0.0.1:8000)
     │  SSE : reasoning_delta · content_delta · agent_tool_call/result ·
     │        research_plan/step · generation_stats
     ▼
FastAPI — chat/server/main.py
     ├─► Orchestrateur agentique — core/agent/
     │     boucle THINK → outils → FINAL, budget, anti-boucle, nudges
     ├─► Runtime llama.cpp — core/inference/ : superviseur du llama-server
     │     en mode router (--models-preset), profils Gemma 4 QAT chargés à
     │     la demande, MTP, KV quantifié, client OpenAI-compatible
     ├─► Outils plateforme — core/runner/ (Python Docker), core/rag/,
     │     core/files/, core/artifacts/, core/memory/
     └─► Recherche — MCP Exa + Brave + Tavily ; fraîcheur locale
           (sport, météo, actu tech, Wikipédia) ; autres MCP selon le modèle
```

## Prérequis

- **Python ≥ 3.11**
- **llama.cpp compilé avec CUDA** : le superviseur cherche `llama-server.exe`
  dans `~/llama.cpp/build/bin/Release/` puis le `PATH` (`LLAMA_SERVER_PATH`)
- **Docker Desktop** (optionnel) : uniquement pour le runner Python isolé
- **Node.js** (`npx`) : Exa, Brave, Tavily, Context7, GitHub, fichiers
  sandbox et graphiques. **uv** (`uvx`) : arXiv, lecture de pages de
  repli, Git, SQLite et fuseaux. La fraîcheur locale (sport, météo, actu
  tech, Wikipédia) est un serveur Python du dépôt, sans clé.
- **Clés API optionnelles** : Exa, Brave, Tavily ; Context7 et GitHub si
  ces MCP sont utilisés. Sans clé, le moteur correspondant ne démarre pas.

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
`docker build -t lasme-python-runner:latest .\infra\runner`.

## Configuration

`core/config.py` charge `.env` au démarrage. Le catalogue MCP lit ensuite
les clés dans l'environnement, sans les journaliser. Le modèle des variables
est `.env.example` ; la copie locale, avec les vraies clés, est `.env`.

```text
# Runtime llama.cpp
LLAMA_SERVER_PATH=            # vide = découverte auto (~/llama.cpp puis PATH)
LLAMA_BASE_URL=http://127.0.0.1:8080   # (= LLAMA_HOST:LLAMA_PORT)
LLAMA_MODELS_MAX=2            # modèles chargés simultanément par le router
# Modèles = profils du router (gemma-4-12b / e4b / e2b / 12b-256k) ;
# les alias Ollama historiques restent acceptés et routés sur ces profils
CHAT_MODEL=gemma-4-12b
FAST_MODEL=gemma-4-e4b
REASONING_MODEL=gemma-4-12b
CODING_MODEL=gemma-4-12b
VISION_MODEL=gemma-4-12b
# Recherche web MCP (toutes optionnelles)
EXA_API_KEY=
BRAVE_SEARCH_API_KEY=         # Brave MCP
TAVILY_API_KEY=
CONTEXT7_API_KEY=             # optionnel
GITHUB_PERSONAL_ACCESS_TOKEN= # optionnel ; GITHUB_TOKEN accepté en secours
LASME_MCP_ENABLED=            # vide = activé ; 0/false/off/no coupe tout
LASME_MCP_DISABLED=           # ids à omettre, séparés par des virgules
LASME_MCP_FS_ROOT=            # sandbox filesystem, pas la racine du dépôt
LASME_MCP_SQLITE_PATH=
LASME_MCP_GIT_REPO=
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
`EXTRA_MODELS`, `HF_HOME`, et `LLAMA_HOST`/`LLAMA_PORT` (composent
`LLAMA_BASE_URL` si elle est absente).

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

Arrêt : `python -m scripts.serve stop` (router) et `.\scripts\stop_local.ps1`
(API). Pilotage : `status`, `metrics --model <profil>`, `info`. Ouvrir
ensuite <http://127.0.0.1:8000/>.

## Modèles et performances

Quatre profils Gemma 4 QAT servis par un seul llama-server en mode router,
présentés dans l'interface du plus faible au plus fort : E2B → E4B → 12B
(défaut) → 12B 256K. **Aucun modèle n'est préchargé au démarrage** : sur
16 Go, le 12B seul demande 12,9 GiB et tout profil résident faisait crasher
le fitting du draft MTP — chaque profil charge donc à la demande
(`LLAMA_MODELS_MAX` instances simultanées), ce qui ajoute quelques secondes
à la première question. Mesures Phase 0 sur RTX 4070 Ti SUPER 16 Go :

| Profil | Contexte | Rôle | Débit mesuré |
| --- | --- | --- | ---: |
| `gemma-4-12b` (défaut) | 128K | qualité/agent, vision native | 211 tok/s |
| `gemma-4-e4b` | 64K | rapide | 129 tok/s |
| `gemma-4-e2b` | 32K | minimal | 214 tok/s |
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

# Tout en une commande ; --live ajoute évals agent + budgets perf (router requis)
.\.venv\Scripts\python.exe -m scripts.validate_all [--live]
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
  (`core/agent/tools.py`) ; routes de codage et outils destructifs
  désactivés par défaut ; toute API passant par un proxy exige
  `LASME_ACCESS_TOKEN`.

Détails : [docs/SECURITY.md](docs/SECURITY.md).

## Licence

Lasme LLM est distribué sous [Apache License 2.0](LICENSE). Voir
[NOTICE](NOTICE) pour les attributions des ressources navigateur (DOMPurify,
highlight.js, KaTeX, marked, Mermaid) et [CHANGELOG.md](CHANGELOG.md) pour
l'historique des versions.
