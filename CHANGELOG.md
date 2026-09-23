# Changelog

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
