# Changelog

## 1.2.0 — Productivité souveraine : Recherche FTS5, Pont Python → Canvas, Duel, Audio, Export & Missions (2026-10-25)

### Six nouvelles fonctionnalités intégrées de bout en bout

- **Recherche plein texte instantanée (`Ctrl+K` + SQLite FTS5) & Conversations épinglées (`📌`)** :
  table virtuelle `messages_fts` synchronisée par triggers SQLite, recherche
  unifiée sur les titres de sessions, le corps des messages (extraits `<mark>`)
  et les artefacts Canvas (`GET /api/sessions/search`), et épinglage des
  conversations prioritaires (`PUT /api/sessions/{session_id}`).
- **Pont visuel direct `python_run` → Chat & Canvas** :
  récolte automatique des graphiques et fichiers générés dans le répertoire de
  travail du sandbox Python (`SubprocessPythonRunner` et pool Docker),
  propagation temps réel dans `agent_tool_result.files` et persistance dans
  `message_metadata["runner_files"]`. Affichage d'une galerie interactive sous
  la réponse avec ouverture directe des figures et tableaux CSV/TSV dans le
  panneau **Canvas**.
- **Export & Import souverain de conversations (`.html`, `.pdf`, `.md`, `.json`)** :
  nouvel exportateur `export_session_conversation` (`GET /api/sessions/{id}/export`)
  générant une page HTML autonome hors-ligne (thème *Forêt & sauge*, sources et
  figures), un rapport PDF A4, un fichier Markdown sourcé ou une archive JSON
  réimportable (`POST /api/sessions/import`).
- **Mode « Duel / Comparaison » de modèles et d'efforts (`⚔️ Duel`)** :
  route `POST /api/chat/compare` exécutant séquentiellement deux configurations
  (ex. `gemma-4-e4b · low` vs `gemma-4-12b · high`) dans le respect du budget
  de 16 Go de VRAM, avec affichage côte à côte des métriques (`tok/s`, durée,
  tokens) et adoption en un clic dans le Chat ou le Canvas.
- **Audio 100 % local : Dictée vocale (STT) & Lecture des réponses (TTS)** :
  synthèse vocale locale (`🔊 Écouter`) sur chaque message assistant avec
  nettoyage Markdown, bouton microphone de dictée vocale dans le compositeur
  et point d'entrée `POST /api/media/transcribe`.
- **Veilles & Missions planifiées d'Agent (`⏰ Missions`)** :
  table `scheduled_missions`, job durable `"agent_mission"` dans `JobStore` /
  `chat.worker.loop`, routes CRUD `/api/missions` + exécution immédiate
  `POST /api/missions/{id}/run` déposant automatiquement un dossier de
  recherche dans le **Canvas**.

## 1.1.0 — Harnais de réponse fiable et identité visuelle (2026-09-26)

### Le harnais ne sacrifie plus la réponse

Trois défauts se cumulaient et donnaient le même symptôme : **une réponse
s'écrit à l'écran, puis disparaît**.

- **Le refus nucléaire est remplacé par une politique graduée.** Quand le
  contrôle de fiabilité ne trouvait aucune page lue *pendant le tour courant*,
  il remplaçait **l'intégralité** de la réponse par un refus administratif
  (« Je n'ai pas pu vérifier ce point… »). Le cas le plus visible : une
  **relance** — « et par rapport à X ? » — répondue avec les faits déjà
  sourcés du fil, donc sans nouvel outil, donc « non vérifiée ». Désormais :
  seules les valeurs numériques absentes des preuves sont assagies, phrase par
  phrase.
- **Les preuves élargies au fil de la conversation.** Une relance s'appuie sur
  les pages lues, les résultats de recherche du tour **et les sources déjà
  citées plus tôt** (nouvelle lecture `db.get_recent_assistant_sources`).
- **Nouvelle règle de prompt « Relance »** : une demande qui découle d'un tour
  précédent se traite avec les faits établis, sans se retirer.
- **La mise en page survit à l'assagissement.** L'ancienne réécriture
  recollait les phrases avec des espaces et **aplatissait les listes markdown**
  (trois puces fondues en un paragraphe, astérisques visibles). Désormais le
  découpage préserve les séparateurs, ne franchit jamais un saut de ligne, ne
  coupe pas un numéro de version en deux (« Terminal-Bench 4.0 »), et remplace
  une valeur fautive par « non vérifié » dans une ligne de tableau.
- **Plus de réponse tronquée à l'écran.** `progressive-renderer.js` révélait le
  texte frame par frame — or un `requestAnimationFrame` armé onglet visible ne
  se déclenche **jamais** si l'onglet devient masqué, et les navigateurs
  **étranglent les minuteurs** d'un onglet masqué (1/s, puis 1/min). La
  révélation n'atteignait jamais la fin : 199 caractères affichés pour 700
  enregistrés. La fin de flux et les corrections serveur sont maintenant
  peintes **d'un bloc**, et un filet de sécurité (frame + minuterie) couvre le
  flux en cours.
- **Règles du prompt système renumérotées 1→19.** Les retouches successives
  avaient produit trois « 11 », deux « 13 » et une règle « 18 » placée avant
  « 15 ». Un test garde désormais l'unicité et l'ordre (`[11]`/`[12]`).

### Identité visuelle

L'ancienne identité (éclair blanc sur dégradé vert→indigo, accent `#10A37F`)
reprenait **le vert d'OpenAI** et les fonds de ChatGPT — le signal « copie » le
plus visible du produit. Remplacée intégralement :

- **Symbole « Bloc »** : un « L » gravé dans une pastille pleine, lisible de
  16 px (favicon) à 512 px.
- **Wordmark capitales** : `LASME` espacé + pastille `LLM`, sans police web
  (la page est hors ligne).
- **Palette « Forêt & sauge »** : `--accent #5E8C72`, `--accent-strong #466F5A`
  pour les boutons portant du texte blanc (contraste ≥ 5:1), `--brand-ink
  #12241C`. Thème nuit : accent éclairci `#7FB495`, pastille inversée.
- **Favicon** : pastille pleine et `prefers-color-scheme` géré **dans le SVG**,
  sinon l'icône disparaît sur une barre d'onglets en thème sombre.
- Balayage complet : plus aucune occurrence de `#10A37F`, `#6366F1`,
  `#10B981`, `#2563EB`, `#1A73E8` ni `#7C6FFF` dans le front.

### Recherche web : dire la vérité sur son état

- Les moteurs réellement configurés sont distingués d'un échec de recherche :
  un `web_research` sans résultat ne peut plus être presenté au modèle comme un
  succès vide — c'est une **erreur d'outil** explicite.
- L'état de la recherche est annoncé une fois, et seulement quand il demande
  une action (« non configurée »). Afficher « Recherche Web désactivée » sur
  une salutation n'était que du bruit.
- La recherche approfondie remonte ses erreurs au lieu de rendre un rapport
  vide, et respecte l'effort de raisonnement demandé.

### Outillage et propreté

- **`scripts/validate_all.py` découvre ses listes de fichiers** au lieu de les
  écrire en dur : une liste figée survit à la suppression d'un module et fait
  échouer la CI sur un vestige (cas réel avec `chat/web/agent.js`).
- **CI GitHub** (`.github/workflows/ci.yml`) : Linux (3.11, 3.13) et Windows
  (3.12), exécutant `validate_all` — exactement la commande locale.
- **Base de données injectable** : `LASME_DATABASE_PATH` permet de faire
  tourner une instance isolée (tests, capture, démonstration) sans toucher au
  fichier de l'utilisateur.
- Retirés : page « Console Agent » non liée depuis l'interface (remplacée par
  le bouton *Déroulé agent* intégré), client API jamais chargé, captures de
  l'ancien design, fichier `git` de 0 octet versionné par erreur.

## Refonte modulaire — phases A→E (2026-09-25)

Découpage du monolithe en monolithe modulaire, sans changement de
comportement : la suite de tests historique (228 pytest + 35 subtests)
passe **sans modification des assertions**.

- **`chat/server/main.py` : 4 300 → ~150 lignes.** C'est devenu la racine
  de composition (dépendances + middleware de sécurité patchable + réexport
  des symboles historiques des tests). Le corps est découpé en :
  - `chat/contracts/` — schémas Pydantic + **contrat SSE versionné**
    (`sse_events.py`) ;
  - `chat/server/services/` — `text` (nettoyage/citations), `sources`
    (extraction des sources agent), `stats` (tok/s, TTFT), `heuristics`
    (social, actualité, profondeur), `background` (titrage, compaction,
    mémoire personnelle) ;
  - `chat/server/modules/<domaine>/routes.py` — `workspace`, `documents`,
    `files`, `artifacts`, `runner`, `research`, `chat`, `coding`, `media` ;
  - `chat/server/app.py` — la factory `create_app(deps, http_dispatch)` ;
  - `chat/server/deps.py` — injection de dépendances à **résolution
    tardive** (les coutures de tests `patch("chat.server.main.*")`
    historiques restent visibles, y compris `db`/`rag_store`).
- **File de jobs durable + worker (D2/E)** : `core/memory/jobs.py`
  (enqueue / claim atomique / complete / fail / requeue des jobs orphelins)
  et `chat/worker/` (loop + handlers + binaire `python -m chat.worker`,
  arrêt propre SIGINT + checkpoint WAL). Le lifespan lance le loop en
  process : titrage, compaction, mémoire et indexation documentaire sont
  des jobs **persistés, rejouables, observables** (fin des
  `asyncio.create_task` nus). Health enrichi : `checks.worker`.
- **Garde-fous (A2/A3/B3)** : surface HTTP figée
  (`tests/snapshots/api_routes.json` + `tests/test_api_contract.py`),
  conformité des événements SSE émis avec le contrat, smoke
  `tests/test_app_factory.py`, et **matrice de dépendances entre couches**
  contrôlée par `scripts/check_imports.py` (8ᵉ étape de `validate_all` :
  `core/` ne dépend jamais de `chat/`, les contrats jamais du serveur…).
- **Stockage (D1/D3)** : façades repositories par domaine
  (`core/memory/repos.py`) et ADR-001 (SQLite unique, un seul écrivain,
  `-wal` jamais supprimé).
- **Front (C)** : 18 modules `chat/web/src/**`, découpés à comportement
  identique (`app.js` 5 493 → 102 lignes). Le client API unique
  (`chat/web/src/api/client.js`) préparé pendant cette phase a été **retiré
  depuis** : jamais chargé par l'interface, donc code mort — la migration des
  appels `fetch` du front vers une couture unique reste un chantier ouvert.

## Audit complet — corrections (2026-09-24)

- **Streaming réel de la réponse** : les `content_delta` partent au fil de la
  génération, au lieu d'être accumulés puis rejoués à la fin du run. Le texte
  d'un tour suivi d'outils (narration) ou écarté par le harnais n'est plus
  jeté : il est archivé dans le panneau de réflexion comme « préambule »
  (`content_reset`). En fin de run, `content_replace` sert la version assainie
  (citations `[n]` vérifiées, section « Sources » retirée) : le texte visible
  est exactement celui qui est persisté. Le TTFT est mesuré au premier delta
  réellement diffusé.
- **Génération d'images** : `LASME_ENABLE_EXTERNAL_IMAGE_GENERATION` est
  désormais **désactivée par défaut** — l'outil Pollinations envoie le prompt
  à un service externe, contraire à la promesse « 100 % local ». Opt-in
  explicite dans `.env`.
- **Garde-fou numérique rétabli** : le contrôle `unsupported_grounded_numbers`
  vivait dans un bloc mort (`buffer_grounded_output` était toujours faux) —
  il s'applique maintenant réellement aux demandes à grounding strict avec
  sources, avant publication de la réponse.
- **Arrêt propre SQLite** : `PRAGMA wal_checkpoint(TRUNCATE)` à la fermeture
  de l'application + `wal_autocheckpoint = 64` par connexion. Avertissement
  `-wal`/`-shm` ajouté au `.gitignore`.
- **CLI coding réparée** : le callback accepte les 3 arguments réellement
  envoyés par `coding/agent.py` (un `TypeError` était garanti au premier
  événement de `python -m coding.cli run`). Nouveaux tests
  `tests/test_coding_agent.py` (callback, confinement fs, listes blanches
  des sous-agents) et `tests/test_db_checkpoint.py`.
- **Nettoyage** : `scripts/install_fast_models.ps1` supprimé (ère Ollama),
  alias de routes `/api/coding/file-tree|file-content|save-file` retirés,
  libellés « Ollama » fantômes remplacés (health `checks.llama`, description
  du paquet, messages UI, aide de la CLI).

## MCP — recherche web (2026-09-23)

La recherche web native (DuckDuckGo, Monid/tinyfish, GDELT, OpenAlex,
Wikimedia, Brave/Tavily en HTTP direct, `fetch_pages`) est retirée.
La recherche passe par les MCP Exa, Brave et Tavily combinés ; la
fraîcheur sport, météo, actu tech et Wikipédia par le serveur MCP local.
Les autres MCP (Context7, GitHub, Git, filesystem sandbox, SQLite,
graphiques AntV, fuseaux) dépendent du modèle : e2b minimal, e4b
intermédiaire, 12b complet. Les outils natifs calculate, current_time,
python_run, RAG, fichiers projet, artefacts et vision restent.
L'agent appelle `web_research` puis `web_read`.

La réponse n'est affichée qu'à la fin du tour d'agent. Le catalogue MCP
est mis en cache. Le titre de conversation ne demande plus qu'une courte
génération sans raisonnement, pour ne pas occuper le GPU pendant la
réponse. Le rendu progressif rattrape le texte plus vite.

## v2 — Plateforme agentique (2026-09-23)

Refonte complète de l'application : chat local agentique type ChatGPT,
runtime llama.cpp, recherche web souveraine. État figé avant l'intégration
des serveurs MCP.

### Runtime & modèles
- Migration Ollama → **llama.cpp** (build local CUDA + FlashAttention), routeur
  multi-profils (`--models-preset`) avec Gemma 4 : 12B (qualité/agent, 128K),
  E4B, E2B, 12B 256K (KV q8_0)
- Speculative decoding MTP (n=4), benchmarks à température 0
  (`scripts/check_perf.py`, budgets 129–217 tok/s mesurés)
- Fin du préchargement des modèles : tout charge à la demande (le 12B seul
  demande 12,9 GiB — tout modèle résident faisait crasher le fitting du draft)

### Plateforme agentique
- Le chat à `/` EST l'agent : boucle d'orchestrateur multi-tours (6 tours,
  budget d'outils 2 048 → 12 288, anti-boucle, nudges)
- 13 outils : web_search, fetch_pages, python_run (pool Docker chaud),
  calculate, analyze_image, rag_search, files_list/read_text,
  artifact_create/update/list, current_time, echo
- Harnais : search→read→cite obligatoire (auto-fetch des URLs si le modèle
  ne le fait pas), citations W5 (une URL citée doit avoir été vue)
- Portail d'actualité : `is_recency_sensitive` force la recherche sur les
  questions sensibles au temps (6 familles de motifs)
- Panneau de Réflexion streamé (mi-hauteur + auto-scroll, repli total),
  isolation raisonnement/réponse, efforts Low/Medium/High (slider segmenté)

### Recherche web
- **Monid (tinyfish) source prioritaire** — gratuite, contrat réel vérifié
  (sync 200 + polling 202, cache endpoint 24 h, garde-fou
  `MONID_MAX_PRICE_USD`, clé jamais loggée)
- Recherche croisée : tinyfish + moteur secondaire (context.dev selon prix)
  en parallèle, fusion dédupliquée (~0,0009 $/recherche)
- Fin de la dépendance Docker/SearXNG ; Sonar/Perplexity skippé pour l'agent

### Interface
- Citations style ChatGPT : marqueurs `[n]` globaux résolus en puces favicon
  à l'endroit de la citation, carte au survol (titre, domaine, pagination)
- Streaming multi-chats parallèle : changer de chat n'interrompt jamais un
  flux ; reprise live à la ré-entrée
- Édition d'un message envoyé = régénération dans le même fil
- Titres de conversations générés par le modèle (résumé propre, langue de
  l'utilisateur, majuscule, apostrophes préservées), produits en live
- Rendu KaTeX complet (matrices pmatrix incluses), stats honnêtes
  (tok/s = décodage réel, hors outils)

### Qualité
- Suite de tests : 266 verts (pytest) + 13 tests JS
- Validation live `scripts/validate_all.py --live` (10 étapes)
- Purge des rapports de refonte ; README réécrit sur la v2
