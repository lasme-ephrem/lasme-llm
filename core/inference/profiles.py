from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Union


@dataclass(frozen=True)
class ModelProfile:
    """Runtime settings tuned for one local model and the available GPU."""

    temperature: float
    num_ctx: int
    num_predict: int
    history_tokens: int
    system_addendum: str
    think: Union[bool, str] = True
    keep_alive: Union[str, int] = "15m"
    options: Dict[str, Any] = field(default_factory=dict)


# Gemma 4 Chat remains the resident general model. Its authors recommend
# temperature=1, top_p=.95 and top_k=64. The 65,536-token profile was measured
# successfully on the RTX 4070 Ti SUPER with 16 GiB of VRAM.
GEMMA_CHAT_PROFILE = ModelProfile(
    temperature=1.0,
    num_ctx=65_536,
    num_predict=8_192,
    history_tokens=48_000,
    system_addendum=(
        "Tu utilises le profil généraliste Gemma 4 Chat. Privilégie une "
        "conversation naturelle, une synthèse solide et des explications "
        "adaptées au niveau de l'utilisateur. Pour une question complexe, "
        "raisonne silencieusement avant de donner une réponse nette."
    ),
    # Ollama accepts -1 as a numeric sentinel for an indefinitely resident
    # model. The string "-1" is parsed as a duration and rejected because it
    # has no unit.
    keep_alive=-1,
    options={
        "top_p": 0.95,
        "top_k": 64,
        "repeat_penalty": 1.1,
        "repeat_last_n": 256,
    },
)

SMOL_FAST_PROFILE = ModelProfile(
    temperature=0.45,
    num_ctx=32_768,
    num_predict=4_096,
    history_tokens=22_000,
    system_addendum=(
        "Tu utilises le profil Lasme Rapide basé sur SmolLM3. Donne une "
        "réponse concise, structurée et exacte. Utilise le raisonnement long "
        "seulement lorsqu’il apporte un gain réel."
    ),
    think=False,
    keep_alive="20m",
    options={
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.08,
        "repeat_last_n": 256,
    },
)

QWEN_VISION_PROFILE = ModelProfile(
    temperature=0.35,
    num_ctx=16_384,
    num_predict=6_144,
    history_tokens=10_500,
    system_addendum=(
        "Tu utilises le profil Lasme Vision basé sur Qwen3-VL. Analyse les "
        "images, documents visuels, tableaux, interfaces et graphiques avec "
        "précision. Pour le texte et le code, distingue les observations "
        "certaines des déductions et vérifie le résultat avant de répondre."
    ),
    think=False,
    keep_alive="8m",
    options={
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.08,
        "repeat_last_n": 256,
    },
)

GEMMA_FABLE_PROFILE = ModelProfile(
    temperature=1.0,
    num_ctx=65_536,
    num_predict=8_192,
    history_tokens=48_000,
    system_addendum=(
        "Tu utilises le profil technique et agentique Gemma 4 Fable. Pour les "
        "problèmes complexes, inspecte d'abord les éléments disponibles, "
        "distingue faits et hypothèses, construis une solution en plusieurs "
        "étapes puis vérifie le résultat avant de répondre. N'invente jamais "
        "un fichier, une commande exécutée, un résultat d'outil ou une source."
    ),
    options={
        "top_p": 0.95,
        "top_k": 64,
        "repeat_penalty": 1.1,
        "repeat_last_n": 256,
    },
)

# Muse Glimmer 30B (q4_K_M-dflash) is the resident agentic model. Measured
# on the RTX 4070 Ti SUPER with 16 GiB of VRAM: ~19 tok/s with flash
# attention, ~15.9/16.4 GiB VRAM. The DFlash draft needs Ollama's automatic
# GPU offload: forcing num_gpu breaks llama.cpp memory fitting, so the client
# must NOT send num_gpu for this model. A 16K context keeps the KV cache
# small enough for the 18 GB of weights + the 1.6 GB DFlash draft.
GLIMMER_PROFILE = ModelProfile(
    temperature=0.35,
    num_ctx=16_384,
    num_predict=8_192,
    history_tokens=12_000,
    system_addendum=(
        "Tu utilises le profil agentique Muse Glimmer. Pour toute question "
        "factuelle ou récente, utilise les outils de recherche Web quand ils "
        "sont disponibles et vérifie tes affirmations. Distingue ce que tu "
        "sais de ce que tu déduis. Produis des réponses sourcées et nettes."
    ),
    keep_alive="15m",
    options={
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.08,
        "repeat_last_n": 256,
    },
)


def get_model_profile(model: str) -> ModelProfile:
    normalized = (model or "").lower()
    if "glimmer" in normalized:
        return GLIMMER_PROFILE
    if "smol" in normalized:
        return SMOL_FAST_PROFILE
    if "qwen" in normalized or "vision" in normalized:
        return QWEN_VISION_PROFILE
    if "fable" in normalized:
        return GEMMA_FABLE_PROFILE
    return GEMMA_CHAT_PROFILE
