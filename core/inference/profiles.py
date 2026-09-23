"""Runtime profiles for the llama.cpp v2 inference layer.

Two concerns live here:

- ``RuntimeProfile`` describes how a model is *served* by llama-server
  (HF repo, context, KV quantization, speculative decoding, VRAM budget).
  The supervisor derives the router INI preset from these.
- ``ModelProfile`` keeps the legacy *chat tuning* shape (sampling,
  history budget, system addendum) consumed by ``chat.server.main``.
  ``get_model_profile`` maps any model string — including legacy Ollama
  aliases — onto the v2 profiles so the existing server keeps working.

All numbers come from Phase 0 measurements on the RTX 4070 Ti SUPER
(16 GiB).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Union

QUALITY_MODEL = "gemma-4-12b"
FAST_MODEL = "gemma-4-e4b"
MINIMAL_MODEL = "gemma-4-e2b"
MAX_CONTEXT_MODEL = "gemma-4-12b-256k"

# Model names that may still be stored in old sessions/projects. They are
# accepted by the API and resolved onto the v2 profiles, never rejected.
LEGACY_MODEL_ALIASES = frozenset(
    {
        "gemma-4-chat",
        "gemma-4-fable",
        "lasme-smol-fast",
        "lasme-qwen-vision",
        "muse-glimmer:30b-q4_K_M-dflash",
    }
)


@dataclass(frozen=True)
class RuntimeProfile:
    """Serving description of one model behind the llama.cpp router."""

    id: str
    hf_repo: str
    context: int
    vram_budget_mib: int
    resident: bool = False
    kv_quant: str = "f16"  # q4_0 forbidden: degrades tool calling
    mtp: bool = True
    mtp_n: int = 4
    description: str = ""

    @property
    def hf_ref(self) -> str:
        return self.hf_repo

    def preset_section(self) -> Dict[str, Any]:
        """INI keys for the router preset (see core/inference/preset.py)."""
        section: Dict[str, Any] = {
            "hf-repo": self.hf_repo,
            "c": self.context,
        }
        if self.kv_quant != "f16":
            section["cache-type-k"] = self.kv_quant
            section["cache-type-v"] = self.kv_quant
        if self.mtp:
            section["spec-type"] = "draft-mtp"
            section["spec-draft-n-max"] = self.mtp_n
        if self.resident:
            section["load-on-startup"] = True
        return section


# Phase 0 measured: 12B + MTP4 + 128K f16 KV = 12.9 GiB total GPU.
RUNTIME_PROFILES: Dict[str, RuntimeProfile] = {
    profile.id: profile
    for profile in [
        RuntimeProfile(
            id=QUALITY_MODEL,
            hf_repo="unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL",
            context=131_072,
            vram_budget_mib=13_100,
            resident=False,  # loaded on demand (~27 s)
            description="12B QAT — qualité/agent, 211 tok/s mesurés",
        ),
        RuntimeProfile(
            id=FAST_MODEL,
            hf_repo="unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL",
            context=65_536,
            vram_budget_mib=8_200,
            resident=False,  # pas résident : 12B (12,9 GiB) + E4B > 16 Go
            description="E4B QAT — vitesse, 129 tok/s mesurés",
        ),
        RuntimeProfile(
            id=MINIMAL_MODEL,
            hf_repo="unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL",
            context=32_768,
            vram_budget_mib=4_800,
            resident=False,  # idem : chargé à la demande
            description="E2B QAT — minimal viable, 214 tok/s mesurés",
        ),
        RuntimeProfile(
            id=MAX_CONTEXT_MODEL,
            hf_repo="unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL",
            context=262_144,
            vram_budget_mib=13_700,
            resident=False,
            kv_quant="q8_0",
            description="12B QAT — 256K tokens, 162 tok/s mesurés",
        ),
    ]
}


def resolve_runtime_profile(model: str | None) -> RuntimeProfile:
    """Map any model string (v2 id or legacy Ollama alias) to a profile.

    Legacy names collapse onto the v2 trio: the platform exposes three
    speeds of the same Gemma 4 family instead of heterogeneous models.
    """
    normalized = (model or "").lower()
    if "256k" in normalized or "max-context" in normalized:
        return RUNTIME_PROFILES[MAX_CONTEXT_MODEL]
    if "e2b" in normalized or "minimal" in normalized:
        return RUNTIME_PROFILES[MINIMAL_MODEL]
    if "e4b" in normalized or "smol" in normalized or "fast" in normalized:
        return RUNTIME_PROFILES[FAST_MODEL]
    # gemma-4-chat, muse-glimmer, qwen-vision, fable, unknown → quality.
    return RUNTIME_PROFILES[QUALITY_MODEL]


def resident_profiles(vram_total_mib: int | None = None) -> list[RuntimeProfile]:
    """Profiles to preload at router startup.

    Always empty: on a 16 GiB GPU the quality 12B alone needs 12.9 GiB
    (weights + MTP draft + 128K f16 KV). Any resident E-model leaves too
    little headroom, and llama.cpp's speculative-draft memory fitting
    crashes with "invalid vector subscript" instead of a clean OOM —
    which surfaces to users as an interrupted generation. Every profile
    loads on demand; E-models load in well under 30 s.
    """
    return []


@dataclass(frozen=True)
class ModelProfile:
    """Legacy chat-tuning shape consumed by chat.server.main."""

    temperature: float
    num_ctx: int
    num_predict: int
    history_tokens: int
    system_addendum: str
    think: Union[bool, str] = True
    keep_alive: Union[str, int] = "15m"
    options: Dict[str, Any] = field(default_factory=dict)
    runtime_id: str = QUALITY_MODEL


GEMMA4_CHAT_PROFILE = ModelProfile(
    temperature=0.7,
    num_ctx=131_072,
    num_predict=8_192,
    history_tokens=60_000,
    system_addendum=(
        "Tu utilises le profil Gemma 4 12B de Lasme. Produis des réponses "
        "naturelles, structurées et exactes. Pour une question complexe, "
        "raisonne avant de répondre et vérifie tes affirmations."
    ),
    options={"top_p": 0.95, "top_k": 64},
    runtime_id=QUALITY_MODEL,
)

GEMMA4_FAST_PROFILE = ModelProfile(
    temperature=0.5,
    num_ctx=65_536,
    num_predict=4_096,
    history_tokens=30_000,
    system_addendum=(
        "Tu utilises le profil Lasme Rapide basé sur Gemma 4 E4B. Donne "
        "une réponse concise, structurée et exacte."
    ),
    think=False,
    options={"top_p": 0.9, "top_k": 40},
    runtime_id=FAST_MODEL,
)

GEMMA4_MINIMAL_PROFILE = ModelProfile(
    temperature=0.5,
    num_ctx=32_768,
    num_predict=3_072,
    history_tokens=16_000,
    system_addendum=(
        "Tu utilises le profil Lasme Minimal basé sur Gemma 4 E2B. "
        "Réponds de façon courte et directe."
    ),
    think=False,
    options={"top_p": 0.9, "top_k": 40},
    runtime_id=MINIMAL_MODEL,
)


def get_model_profile(model: str) -> ModelProfile:
    """Legacy entry point: chat tuning for any model string."""
    runtime = resolve_runtime_profile(model)
    if runtime.id == FAST_MODEL:
        return GEMMA4_FAST_PROFILE
    if runtime.id == MINIMAL_MODEL:
        return GEMMA4_MINIMAL_PROFILE
    return GEMMA4_CHAT_PROFILE
