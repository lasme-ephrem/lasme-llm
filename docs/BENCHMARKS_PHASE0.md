# Benchmarks Phase 0 — preuves et mesures (2026-09-19)

Machine : RTX 4070 Ti SUPER (16 376 MiB), Windows, llama.cpp **b10358**
(030ebb558, MSVC x64, CUDA + Flash Attention) — build local existant.
Modèles : `unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL`,
`unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL` (QAT Google).
Harness : `scripts/bench_phase0.py` (mesures exactes côté serveur via
`/completion`, TTFT client sur SSE chat, scénarios d'outils validés par
schéma). Résultats bruts : `.models/logs/bench_results.jsonl`.
VRAM mesurée = usage GPU total (baseline système ≈ 1,8 Go incluse).

## Verdict exécutif

**GO pour la Phase 1.** Toutes les cibles indicatives de la roadmap sont
dépassées, souvent d'un facteur 2 à 5 :

| Cible roadmap | Mesuré | Marge |
| --- | --- | --- |
| 12B qualité ≥ 40 tok/s | **211 tok/s** (MTP n=4, 128K) | ×5,3 |
| 12B TTFT ≤ 400 ms (préfixe caché) | **231 ms @ 31 559 tokens** | ×1,7 |
| E4B vitesse ≥ 80 tok/s | **129 tok/s** | ×1,6 |
| E4B TTFT ≤ 250 ms | **98 ms @ 31 559 tokens** | ×2,6 |
| 256K contexte « à valider » | **Tient : 13,4 Go / 16,4, 162 tok/s** | ✅ |

## 1. Débit de génération — 12B (128K, KV f16)

| Config speculative | tok/s (3 runs) | VRAM MiB | Gain vs sans MTP |
| --- | --- | --- | --- |
| sans MTP | 62,3 – 62,8 | 12 355 | — |
| MTP n=2 | 131,5 – 146,2 | 12 791 | ×2,3 |
| **MTP n=4** | **205,6 – 217,0** | **12 915** | **×3,4** |
| MTP n=8 | 204,3 – 231,2 | 12 791 | ×3,6 |

Décision : **MTP n=4 par défaut** (meilleure stabilité inter-runs ;
n=8 apporte un gain marginal et irrégulier).

## 2. Contexte 256K — faisable

Config : `-c 262144 -ctk q8_0 -ctv q8_0`, MTP n=4.

- Charge confirmée (`n_ctx: 262 144` via `/props`) ;
- VRAM : **13 435 MiB / 16 376** (≈ 2,9 Go encore libres) ;
- Débit : 157 – 162 tok/s (−23 % vs KV f16 — coût du doublement de contexte) ;
- `q4_0` KV reste interdit (dégradation tool calling documentée).

## 3. TTFT et prompt caching

12B, MTP n=4, 128K — chat SSE, premier token visible (raisonnement inclus) :

| Préfixe (tokens réels) | TTFT 1er appel (froid) | TTFT 2e appel (chaud) | Gain |
| --- | ---: | ---: | ---: |
| 997 | 1 184 ms | 297 ms | ×4,0 |
| 7 879 | 2 665 ms | 195 ms | ×13,7 |
| 31 559 | 9 690 ms | **231 ms** | ×42 |

E4B, MTP n=4, 128K :

| Préfixe | Froid | Chaud |
| --- | ---: | ---: |
| 997 | 205 ms | 61 ms |
| 7 879 | 1 029 ms | 74 ms |
| 31 559 | 4 184 ms | **98 ms** |

**Preuve du mécanisme** (endpoint natif, 31 540 tokens de préfixe) :
1er appel traite 31 540 tokens (11,9 s, 2 642 tok/s) ; 2e appel
**13 tokens** (232 ms) — le préfixe entier est servi depuis le KV cache.
Conséquence architecture : en boucle agent, chaque tour ne paie que son
delta — le TTFT perçu reste < 300 ms même à 30K tokens d'historique.

## 4. Fiabilité du tool calling

12B, `--jinja`, tools OpenAI, température 0 :

- **0 argument malformé sur 12 scénarios** (aucun JSON invalide, aucun
  outil halluciné, aucune boucle) ;
- 2 « échecs » initiaux requalifiés après inspection :
  - *« météo à Montréal demain »* → le modèle choisit `search_web` car
    `get_weather` n'a pas de paramètre date — sélection d'outil pertinente,
    le scénario de test était mal étiqueté ;
  - *« somme des premiers < 1000 »* → tronqué par `max_tokens=512`
    (`finish_reason=length`) ; appel parfaitement formé à budget 2 048
    (204 tokens consommés) ;
- **Mini-boucle agent (appel → résultat → réponse finale) : 2/2 résolus
  en 2 tours**, sans boucle ;
- E4B : **12/12 OK**, boucle 2/2.

Le « bug agentique » Gemma 4 documenté en juin 2026 **ne se manifeste
pas** sur cette combinaison (QAT GGUF + b10358 + `--jinja`). Le seul
levier réel est la **gestion du budget de tokens** (raisonnement + appel)
— responsabilité de l'orchestrateur (Phase 2) : `finish_reason=length`
sur un tour d'outil ⇒ retry avec budget accru.

## 5. Mode router multi-modèles — validé

Config : `llama-server --models-preset .models/router_models.ini
--models-max 2` (preset : `[*]` global MTP n=4 + sections
`[gemma-4-12b]` 128K, `[gemma-4-e4b]` 64K `load-on-startup`,
`[gemma-4-e2b]` 32K `load-on-startup`).

Résultats :

- Preset INI parsé, **3 profils exposés** dans `/v1/models` ;
- **Chargement au démarrage** confirmé : E4B et E2B montés comme
  instances filles distinctes (logs : `state: ready`, ports internes
  séparés), `--models-max 2` respecté ;
- **Routage par champ `model`** prouvé (logs : `proxying request to
  model gemma-4-e4b on port 60776` / `gemma-4-e2b on port 60775`),
  réponses étiquetées du bon modèle ;
- **Co-résidence E4B (64K) + E2B (32K) : 10,0 Go / 16,4** tout compris,
  12B listé et chargeable à la demande ;
- E2B mesuré à travers le router : **180 – 214 tok/s** ;
- Les modèles du cache HF sont aussi auto-découverts en entrées
  supplémentaires — l'option preset `dedup-cache-models = true`
  (section `[*]`) les masquera en production ;
- Piège relevé : `curl` sous Git Bash/Windows envoie les accents en
  cp1252 (JSON rejeté) — le client Python httpx n'a aucun problème ;
  à noter pour les scripts futurs.

Co-résidence 12B + E4B simultanée à grands contextes confirmée
impossible (~20 Go) → stratégie Phase 1 : E4B + E2B résidents,
12B monté à la demande (charge ~27 s), ou configuration inverse.

## 6. Profils verrouillés (mesurés, pas estimés)

| Profil | Modèle | Contexte | KV | MTP | tok/s | TTFT chaud | VRAM |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| **quality** | 12B QAT | 128K | f16 | n=4 | 211 | 231 ms @31K | 12,9 Go |
| **max-context** | 12B QAT | **256K** | q8_0 | n=4 | 162 | — | 13,4 Go |
| **fast** | E4B QAT | 128K | f16 | n=4 | 129 | 98 ms @31K | 8,1 Go |
| **minimal** | E2B QAT | 32K | f16 | n=4 | **180 – 214** | — | ~3 Go (co-résident mesuré à 10,0 Go avec E4B) |

Chargeur de modèle 12B : ~27 s depuis le cache HF (NVMe).

## 7. Décisions entraînées pour la Phase 1

1. Superviseur en mode router llama-server, preset INI par profils.
2. Co-résidence 12B+E4B à grands contextes impossible (~20 Go) —
   stratégie : E4B résident + 12B chargé à la demande (ou l'inverse selon
   l'usage), `--models-max` et budgets VRAM déclarés par profil.
3. MTP n=4 partout ; KV q8_0 réservé au profil max-context.
4. Le client doit traiter `reasoning_content` (raisonnement par défaut
   du modèle) : timeline UI + `--reasoning-budget` comme levier latence.
5. `finish_reason=length` en tour d'outil = retry budgeté (Phase 2).

## 8. Reproducibilité

```powershell
# 12B profil qualité
C:\Users\lasme\llama.cpp\build\bin\Release\llama-server.exe `
  -hf unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL `
  --spec-type draft-mtp --spec-draft-n-max 4 `
  -ngl 999 -fa on -c 131072 --jinja --metrics `
  --host 127.0.0.1 --port 8080

# harness (venv du projet principal)
python -m scripts.bench_phase0 all --base http://127.0.0.1:8080
```

Variantes mesurées : `--spec-type none` / `--spec-draft-n-max 2|8` ;
256K : `-c 262144 -ctk q8_0 -ctv q8_0` ; E4B : même commande avec
`unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL`.
