# Changelog

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
