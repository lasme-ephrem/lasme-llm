from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class ModelProfile:
    """Runtime settings tuned for one local model and the available GPU."""

    temperature: float
    num_ctx: int
    num_predict: int
    history_tokens: int
    system_addendum: str
    think: bool = True
    keep_alive: str = "15m"
    options: Dict[str, Any] = field(default_factory=dict)


# Gemma 4's authors recommend temperature=1, top_p=.95 and top_k=64.
# Both local quantizations were measured successfully at 65,536 tokens on the
# RTX 4070 Ti SUPER: ~7.2 GiB for Chat and ~9.8 GiB for Fable.
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
    options={
        "top_p": 0.95,
        "top_k": 64,
        "repeat_penalty": 1.1,
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


def get_model_profile(model: str) -> ModelProfile:
    normalized = (model or "").lower()
    if "fable" in normalized:
        return GEMMA_FABLE_PROFILE
    return GEMMA_CHAT_PROFILE
