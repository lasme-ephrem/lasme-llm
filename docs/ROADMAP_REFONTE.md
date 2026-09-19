# Roadmap de refonte — Lasme LLM v2

Plateforme agentique locale sur llama.cpp + Gemma 4, optimisée RTX 4070 Ti
SUPER 16 Go, minimale viable sur toute config GPU ≥ 8 Go.

Date : 2026-09-19. Branche cible : `refonte/v2` (à créer depuis `main`).

---

## 0. Décisions fondatrices (issues de la recherche)

### 0.1 Modèle : Gemma 4 12B QAT — verdict définitif

| Candidat | Taille (GGUF) | Contexte natif | Verdict 16 Go |
| --- | --- | --- | --- |
| **gemma-4-12B-it QAT `UD-Q4_K_XL`** | **6,72 Go** | **256K** | ✅ **Retenu — profil qualité/agent** |
| gemma-4-E4B-it QAT `UD-Q4_K_XL` | 4,22 Go | 128K | ✅ **Retenu — profil vitesse** |
| gemma-4-E2B-it QAT `UD-Q4_K_XL` | 2,62 Go | 128K | ✅ Modèle « minimal viable » configs modestes |
| gemma-4-26B-A4B QAT `UD-Q4_K_XL` | 14,25 Go | 256K | ❌ Ne tient pas (KV + mmproj > 16 Go) |
| gemma-4-31B | ~16+ Go | 256K | ❌ Hors budget |

Les trois modèles retenus partagent la même famille, le même template
(outils, format de raisonnement) et le même drafter MTP : la plateforme
bascule de l'un à l'autre sans changer une ligne de logique agentique.
E4B + mmproj + MTP ≈ 5,3 Go → ~10 Go libres pour KV et compute : très
haut débit et TTFT bas garantis.

Repo HuggingFace : `unsloth/gemma-4-12B-it-qat-GGUF`.

Pourquoi ce choix :
- **QAT** (quantization-aware training par Google) : qualité quasi-fp16 à
  taille 4 bits — bien supérieure à une simple post-quantization.
- **Multimodal natif** (`mmproj` ≈ 0,2 Go) : vision intégrée au modèle
  principal, remplace avantageusement Qwen3-VL en profil séparé.
- **MTP** (`mtp-gemma-4-12B-it.gguf`, 0,25 Go) : drafter Multi-Token
  Prediction auto-détecté par llama.cpp via `-hf` — speculative decoding
  quasi sans perte, partage le KV cache du modèle cible.
- **Function calling natif** dans le template Gemma 4 (256K ctx natif).

Budget VRAM estimé (à valider en Phase 0) :

```text
Poids modèle UD-Q4_K_XL   6,72 Go
mmproj vision             0,20 Go
Drafter MTP               0,25 Go
Compute buffers           ~0,8-1,2 Go
KV cache                  reste disponible ≈ 7-8 Go
─────────────────────────────────────
→ 128K en f16 KV réaliste ; 256K avec -ctk/-ctv q8_0 + SWA hybride
```

⚠️ **Vigilance documentée** : `json-schema-to-grammar` (GBNF) ne contraint
pas complètement les arguments d'outils sur Gemma 4 ; la communauté
(r/LocalLLaMA juin 2026, discussion llama.cpp #21839) rapporte des appels
d'outils malformés et des boucles. **Conséquence architecturale** : la
plateforme ne fera PAS confiance aveuglément aux tool calls du modèle —
validation stricte côté orchestrateur + boucle de réparation + budget de
tours (détail en Phase 2). C'est précisément là qu'un one-man-project
peut faire mieux que les frameworks génériques.

### 0.2 Runtime : llama.cpp natif (abandon d'Ollama)

État vérifié sur la machine :
- `C:\Users\lasme\llama.cpp` — clone récent, **build b10358** (030ebb558)
  de août 2026, MSVC x64, **CUDA ON + Flash Attention ON**,
  `build/bin/Release/llama-server.exe` fonctionnel.
- Le build supporte déjà `--spec-type draft-mtp` (vérifié dans `--help`).

llama-server offre tout ce qu'il faut :
- API **OpenAI-compatible** `/v1/chat/completions` (et Anthropic, embeddings,
  reranking), streaming SSE, continuous batching ;
- **Tool calling natif** via `--jinja` (templates Jinja du GGUF), y compris
  `parallel_tool_calls` ;
- Options 16 Go : `-fa on`, `-ctk q8_0 -ctv q8_0`, `-ngl 999`, `--jinja`,
  `--spec-type draft-mtp --spec-draft-n-max 4`, SWA hybride par défaut.

⚠️ `-ctk q4_0` dégrade mesurablement le tool calling (doc officielle
llama.cpp) → interdit dans nos profils ; q8_0 maximum.

Commande de référence (profil qualité) :

```powershell
C:\Users\lasme\llama.cpp\build\bin\Release\llama-server.exe `
  -hf unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL `
  --spec-type draft-mtp --spec-draft-n-max 4 `
  -ngl 999 -fa on -c 131072 --jinja `
  --host 127.0.0.1 --port 8080
```

### 0.3 Stratégie de performance — tok/s, TTFT, latence de bout en bout

La vitesse d'inférence est une exigence de premier rang, au même titre
que la qualité. Leviers identifiés (tous vérifiés dans la doc llama-server
du build local b10358) :

1. **Speculative decoding MTP** (`--spec-type draft-mtp`) : le drafter
   partage le KV cache du modèle cible et ne change pas la sortie
   (vérification token par token). `--spec-draft-n-max` réglable (2/4/8)
   — le sweep en Phase 0 donne le optimum débit/VRAM.
2. **Prompt caching** (`--cache-prompt`, activé par défaut) : le préfixe
   commun (system prompt + historique stable) n'est pas retraité entre
   les tours → TTFT divisé d'autant en conversation et en boucle agent
   (chaque tour de boucle réutilise le préfixe du tour précédent).
   Compléments : `--cache-reuse N` (réutilisation par KV shifting),
   `--cache-idle-slots` + `--cache-ram` (conservation des slots inactifs).
3. **Flash attention** (`-fa on`), **repack** (activé par défaut),
   KV **q8_0** (`-ctk/-ctv`) : moins de bande passante mémoire, attention
   plus rapide sur long contexte. q4_0 interdit (dégrade le tool calling).
4. **Mode router multi-modèles** (`--models-dir` + `--models-preset` INI +
   `--models-max`) : UN seul llama-server sert 12B, E4B et E2B à la fois,
   routés par le champ `model` de la requête — bascule qualité/vitesse
   sans processus ni rechargement. C'est l'architecture cible de la
   Phase 1 (remplace les 3 « profils Ollama » actuels).
5. **Raisonnement sous contrôle** : `--reasoning-budget N` et
   `--reasoning-effort` limitent les tokens de réflexion (le budget
   raisonnement est un levier TTFT de bout en bout aussi puissant que le
   matériel) ; `--reasoning-format` expose `reasoning_content` séparé,
   parfait pour la timeline UI.
6. **Batching/UX** : `-ub` ajusté au GPU, `--threads-http`, `--warmup`,
   et streaming SSE dès le premier token (le TTFT perçu par
   l'utilisateur EST le produit).

**Cibles indicatives** (à verrouiller avec les mesures Phase 0 ; base :
RTX 4070 Ti SUPER, CUDA, tous poids en VRAM) :

| Profil | Modèle | Contexte | Cible génération | Cible TTFT (préfixe caché) |
| --- | --- | --- | --- | --- |
| Qualité/Agent | 12B + MTP | 128K | ≥ 40 tok/s | ≤ 400 ms |
| Vitesse | E4B + MTP | 64K | ≥ 80 tok/s | ≤ 250 ms |
| Minimal | E2B + MTP | 32K | ≥ 100 tok/s | ≤ 200 ms |

Chaque profil a un budget VRAM déclaré et le superviseur refuse une
combinaison qui dépasse (erreur explicite, pas de swap silencieux).

**Observabilité** : `--metrics` expose un endpoint Prometheus
(`prompt_tokens_seconds`, `predicted_tokens_seconds`, compteurs par
requête) — ingéré par le backend, affiché en continu dans l'UI (comme
les métriques actuelles, enrichies) et stocké pour les évals.

### 0.4 Refonte vs conservation, module par module

| Module existant | Décision | Justification |
| --- | --- | --- |
| `core/security.py` + tests sécurité | **Conserver** (adapter) | Excellent niveau, valide pour llama-server |
| `core/runner/python.py` + Docker | **Conserver** | Sandbox durci, indépendant du runtime |
| `core/files/store.py` (SHA-256, validation) | **Conserver** | Solide |
| `core/artifacts/*` (canvas, exports) | **Conserver** (adapter) | Différenciateur produit |
| `core/tools/web_search.py` + orchestrateur | **Refactorer** | Bon fond, 2 317 lignes à découper ; en faire un outil agent |
| `core/rag/store.py` | **Refactorer** | En faire un outil agent + garde le ranking hybride |
| `core/memory/*` | **Adapter** | Compaction/résumé réutilisé pour la boucle agent |
| `core/inference/client.py` + `profiles.py` | **Réécrire** | API Ollama → OpenAI-compatible + MTP |
| `chat/server/main.py` (4 123 lignes) | **Réécrire** (routers) | Monolithe ; découpage par domaine |
| `chat/web/app.js` (3 964 lignes) | **Réécrire** (modules ES) | UI agent-first nécessaire de toute façon |
| `coding/` (agent CLI) | **Fusionner** | Devient un outil/skill du cœur agentique commun |

---

## Phase 0 — Fondations et validation expérimentale (≈ 1 semaine)

Objectif : verrouiller les hypothèses techniques avant d'écrire la v2.

1. **Hygiène de départ** : corriger les 2 tests rouges (défaut
   `gemma-4-chat` obsolète dans `tests/test_projects_artifacts_research.py`),
   merger `codex/product-workspace-v2` dans `main`, créer `refonte/v2`.
2. **Télécharger le modèle** (llama-server le gère via `-hf`, ou
   `huggingface-cli`) : `unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL`
   + `gemma-4-E4B-it-qat-GGUF` (secondaire).
3. **Benchmarks sur la machine** (`llama-bench` + tests réels) —
   produire la matrice de référence qui verrouille les profils :
   - tok/s génération 12B/E4B/E2B, sans MTP puis
     `--spec-draft-n-max` 2/4/8 (sweep) ;
   - TTFT court contexte vs long contexte (8K/32K/128K de préfixe),
     avec et sans `--cache-prompt` (mesure du gain réel en conversation
     et en boucle agent) ;
   - VRAM réelle à 64K / 128K / 256K, KV f16 vs q8_0 ;
   - effet du `--reasoning-budget` sur la latence de bout en bout ;
   - validation du mode router : 12B + E4B chargés ensemble
     (`--models-max 2`), bascule par champ `model`, VRAM cumulée ;
   - cibles §0.3 atteintes ou ajustées — les chiffres mesurés
     remplacent les cibles indicatives.
4. **Test de fiabilité du tool calling** : script dédié qui joue N scénarios
   d'appels d'outils via `/v1/chat/completions` + `--jinja`, mesure le taux
   d'arguments JSON malformés. Ce chiffre calibre les garde-fous de la
   Phase 2 (validation stricte, réparation, grammaires).
5. **Décision de contexte** : fixer les profils définitifs (qualité/
   équilibré/minimal) à partir des mesures, pas des estimations.

**Porte de sortie** : si le taux d'échec tool calling Gemma 4 12B > ~15 %
non réparable par prompt/grammar, prévoir un profil agentic de secours
(Qwen3-VL 8B déjà connu du projet) — la plateforme est conçue pour être
model-agnostic de toute façon.

## Phase 1 — Couche runtime llama.cpp (≈ 1 à 2 semaines)

1. **`core/inference/` v2** (réécriture) :
   - client OpenAI-compatible (httpx, streaming SSE, `tool_calls` en
     delta, `parallel_tool_calls`, `reasoning_content`) ;
   - superviseur de processus : démarre/surveille/redémarre
     **llama-server en mode router** (`--models-dir` + preset INI généré
     depuis la config des profils), santé, logs, arrêt propre ;
   - gestionnaire de modèles : téléchargement `-hf`, inventaire local,
     budget VRAM déclaré par profil (12B+E4B co-résidents possibles,
     E2B seul sur configs modestes) ;
   - profils (dataclass) : `quality` (12B, 128K+, MTP), `fast` (E4B,
     64K, TTFT minimal), `minimal` (E2B) — auto-détection VRAM pour le
     « minimal viable » sur autre config ;
   - ingestion `--metrics` (Prometheus) : tok/s, TTFT, queue —
     remontés à l'API et stockés.
2. **Scripts** : `start_local.ps1` devient lanceur de llama-server via le
   superviseur Python ; idem `stop_local.ps1`.
3. **Tests** : client mocké (réponses OpenAI factices), superviseur
   (cycle de vie), profils.
4. **Démo interne** : le chat existant parle à llama-server via un shim
   minimal (preuve de migration avant la refonte complète).

## Phase 2 — Cœur agentique (≈ 3 semaines, le gros morceau)

Nouveau package `core/agent/` — la boucle EST le produit :

1. **Orchestrateur = machine à états déterministe** (pas du texte généré) :
   `PLANNING → TOOL_CALL → AWAIT_RESULT → OBSERVE → (boucle) → FINAL`.
   Budget de tours configurable, stop conditions (budget, répétition,
   erreurs), interruption utilisateur à tout instant.
2. **Couche anti-échec Gemma 4** (réponse directe au problème documenté) :
   - schémas JSON stricts par outil + validation `pydantic` ;
   - boucle de réparation : argument invalide → message d'erreur
     structuré renvoyé au modèle (max 2 essais) ;
   - détection de boucle (mêmes tool calls répétés) → divergence forcée ;
   - grammaires GBNF `response_format` pour les outils critiques.
3. **Registre d'outils** : chaque outil = nom, description, schéma JSON,
   politique de sécurité, timeout, mode d'affichage UI. Enregistrement
   déclaratif, tests unitaires obligatoires par outil.
4. **Streaming événementiel** : SSE typés (`reasoning`, `tool_call`,
   `tool_result`, `final`, `error`, `metrics`) — contrat unique
   consommé par le frontend, persisté en base (rejouable).
5. **Mémoire & contexte v2** : réutiliser compaction/résumé de
   `core/memory/` ; contexte monté dynamiquement (tours récents +
   mémoire pertinente + résultats d'outils compressés). Le 128K change
   la donne : moins de compaction agressive, mais toujours nécessaire
   en boucle longue.
6. **Sécurité** : politiques par outil (réseau, fichiers, exec) branchées
   sur `core/security.py` ; les tool calls du modèle sont du contenu
   non fiable, jamais exécutés sans validation.

## Phase 3 — Suite d'outils v2 (≈ 2 semaines, en parallèle de la fin de Phase 2)

Outils du registre, par priorité :

1. `web_search` — refactor de l'orchestrateur existant (Sonar →
   spécialisés → SearXNG → Brave → Tavily → DDG) en un seul outil agent
   avec sous-étapes internes.
2. `fetch_page` — extraction trafilatura + garde-fous SSRF existants.
3. `rag_search` — le RAG v2 exposé comme outil (citations préservées).
4. `python_run` — le runner Docker existant, inchangé côté sécurité.
5. `files_*` — bibliothèque/lecture/écriture via `core/files/store.py`.
6. `analyze_image` — **nouveau** : vision native Gemma 4 via mmproj
   (l'utilisateur attache une image, l'outil la passe au modèle) ;
   remplace le profil Qwen3-VL.
7. `artifact_create/update` — canvas existant piloté par l'agent.
8. `code_run/git` — issus de `coding/` réencapsulés en outils
   (le CLI `coding/` disparaît au profit du cœur commun).
9. **(3b, optionnel)** passerelle MCP : consommer des serveurs MCP
   externes comme source d'outils supplémentaires. MVP = système maison
   (contrôle total), MCP en extension — pas l'inverse.

## Phase 4 — Plateforme & UX agent-first (≈ 2 à 3 semaines)

1. **Backend réécrit en routers** : `chat/server/` éclaté en
   `routers/{chat,agent,projects,files,artifacts,runner,research,admin}.py`
   + `deps.py` (auth, sessions). Fini le monolithe de 4 123 lignes.
2. **Frontend modulaire** (modules ES, plus de fichier unique) :
   - **timeline agent** : chaque tour affiche raisonnement → outils
     appelés (collapsible, args/results) → réponse finale, façon
     ChatGPT moderne ;
   - éditeur d'outils par projet (activer/désactiver, budgets) ;
   - canvas, projets, citations : conservés, rebranchés sur les SSE v2 ;
   - sélecteur de profil (qualité/rapide) à la place du sélecteur
     de modèles multiples.
3. **Métriques d'inférence** conservées et étendues (tok/s, TTFT, VRAM
   remontée par llama-server `/props` + `/metrics`).

## Phase 5 — Qualité, évals et durabilité (≈ 1 à 2 semaines)

1. **Harness d'évals agentiques local** : scénarios rejouables
   (recherche sourcée, génération d'artefact, analyse d'image, code
   sandboxé) avec scoring automatique — extension de
   `scripts/evaluate_models.py`.
2. **Budget de régression performance** : les évals rejouent la matrice
   de benchmarks de la Phase 0 (tok/s, TTFT avec/sans cache, VRAM) à
   chaque changement du socle inference ; toute régression > 10 % sur
   une métrique cible bloque la fusion (CI locale).
3. Suite de tests v2 complète (orchestrateur, garde-fous, routers,
   outils, sécurité) — la barre actuelle (111 tests, 2 s) devient le
   plancher, pas le plafond.
4. Documentation : README v2, `docs/ARCHITECTURE.md`, SECURITY.md mis à
   jour pour llama-server, guide de migration config.
5. Audit sécurité final (auth, sandbox, SSRF, iframe CSP) sur la v2.

---

## Jalons et validation

| Fin de phase | Critère de sortie mesurable |
| --- | --- |
| P0 | Matrice de benchmarks réels publiée (tok/s, TTFT ± cache, VRAM, taux d'échec tool calls) ; cibles §0.3 verrouillées |
| P1 | Chat existant fonctionne 100 % sur llama-server, tests verts |
| P2 | Boucle agent complète en CLI/test : plan → outils → réponse |
| P3 | ≥ 8 outils au registre, chacun testé, évals par outil |
| P4 | UI agent-first utilisable au quotidien, remplace la v1 |
| P5 | Évals automatisées vertes, docs à jour, audit sécurité OK |

## Risques connus et mitigations

| Risque | Mitigation |
| --- | --- |
| Tool calling Gemma 4 malformé (documenté) | Validation stricte + réparation + grammaires + budget de tours (P2) ; profil Qwen de secours |
| 256K impossible en pratique sur 16 Go | Profils gradués dès P0 (128K/f16, 256K/q8_0) ; la plateforme est agnostique du contexte |
| MTP instable selon les versions | `--spec-draft-n-max` ajustable ; fallback sans speculative decoding |
| Périmètre trop large (one-man) | Phases à portes de sortie, conservation max du socle existant (security/runner/files/artifacts), MVP maison avant MCP |
| Ollama encore nécessaire à d'autres usages | Les deux peuvent cohabiter (ports distincts) ; désinstallation libre |

## Sources principales

- [Vue d'ensemble Gemma 4 — Google AI](https://ai.google.dev/gemma/docs/core)
- [unsloth/gemma-4-12B-it-qat-GGUF — HuggingFace](https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF)
- [Guide QAT Gemma 4 — Unsloth](https://unsloth.ai/docs/models/gemma-4/qat)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [Function calling llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- [Discussion « Error-free tool calling » #21839 — llama.cpp](https://github.com/ggml-org/llama.cpp/discussions/21839)
- [Gemma 4 bug fixes and research request — HuggingFace Forums](https://discuss.huggingface.co/t/gemma-4-bug-fixes-and-research-request/176979)
- [Gemma 4 12B tool calling — r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1twmw4o/gemma_4_12b_incompatible_with_opencode_or_just)
- [Meilleurs serveurs MCP 2026 — Firecrawl](https://www.firecrawl.dev/blog/best-mcp-servers-for-developers)
- [Gemma 4 12B on 16GB laptops — The New Stack](https://thenewstack.io)
