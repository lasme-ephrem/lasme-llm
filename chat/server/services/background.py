"""Tâches de fond du chat : titrage, compaction, mémoire personnelle.

Extraits de ``chat/server/main.py`` (refonte modulaire). Ces tâches
s'exécutent en arrière-plan sans jamais bloquer ni casser la réponse.
"""

from __future__ import annotations

import asyncio
import re
from typing import Dict

from core.config import settings
from core.inference.profiles import get_model_profile
from core.memory.compaction import (
    build_compaction_messages,
    compactable_head,
    should_compact,
)
from core.memory.personal import maybe_refresh_generated_memories

from chat.server.deps import deps
from chat.server.services.text import clean_model_text

_memory_update_locks: Dict[str, asyncio.Lock] = {}
_personal_memory_lock = asyncio.Lock()


def sanitize_generated_title(raw: str) -> str:
    """Normalize an LLM-generated conversation title.

    The big labs' standard: a short clean summary, first letter
    capitalized, in the user's language. This keeps French apostrophes
    (d'universalité) instead of gluing words together, strips wrapping
    quotes and "Titre :" prefixes the model sometimes emits.
    """
    title = (raw or "").strip()
    # Le modèle répète parfois un préfixe de consigne : on le retire.
    title = re.sub(r"^(?:titre|title)\s*:\s*", "", title, flags=re.IGNORECASE)
    # Guillemets englobants uniquement — les apostrophes françaises restent.
    title = title.strip(" \t\"'`«»“”«»")
    # Une seule ligne, sans ponctuation finale.
    title = title.splitlines()[0].strip() if title else ""
    title = title.rstrip(" .!?,;:")
    title = re.sub(r"\s+", " ", title)
    if not title:
        return ""
    # Cap propre : jamais de coupe en plein mot (8 mots max).
    words = title.split(" ")
    if len(words) > 8:
        title = " ".join(words[:8])
    # Majuscule sur le premier caractère (accents compris : é → É).
    return title[0].upper() + title[1:]


async def async_generate_and_update_title(session_id: str, prompt: str, model: str):
    """Generates the session title in parallel with the chat stream.

    Pas de sleep initial : la tâche démarre immédiatement et progresse sur
    les autres slots du routeur pendant que la réponse principale streame —
    le titre est prêt quand le flux se termine.
    """
    try:
        title_prompt = [
            {
                "role": "system",
                "content": (
                    "Génère un titre très court (3 à 6 mots) résumant la "
                    "demande de l'utilisateur, DANS LA LANGUE de sa demande. "
                    "Style : un résumé propre, première lettre en majuscule, "
                    "sans guillemets, sans point final, sans préfixe « Titre : » "
                    "— réponds uniquement avec le titre. Conserve les "
                    "apostrophes françaises (d'universalité). N'utilise aucun "
                    "caractère chinois, asiatique ou cyrillique."
                ),
            },
            {"role": "user", "content": prompt[:300]},
        ]
        # Same model as the conversation: the router keeps it loaded, so no
        # expensive swap for a 40-token generation.
        reply = await deps.client.chat(
            model=model,
            messages=title_prompt,
            temperature=0.2,
            num_ctx=2_048,
            think=False,
            num_predict=64,
        )
        clean_title = sanitize_generated_title(
            clean_model_text(reply.get("message", {}).get("content", ""))
        )
        if not clean_title or reply.get("done_reason") == "length":
            # Échantillonnage malchanceux (reasoning a mangé le budget -> vide)
            # ou modèle bavard coupé en plein mot (done_reason=length) : un
            # seul retry avec le double, puis abandon silencieux.
            reply = await deps.client.chat(
                model=model,
                messages=title_prompt,
                temperature=0.2,
                num_ctx=2_048,
                think=False,
                num_predict=96,
            )
            clean_title = sanitize_generated_title(
                clean_model_text(reply.get("message", {}).get("content", ""))
            )
        # Strip CJK, Cyrillic, Hiragana/Katakana & Hangul (accents FR préservés).
        clean_title = re.sub(
            r"[\u4e00-\u9fff\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af]", "",
            clean_title,
        ).strip()

        if clean_title and len(clean_title) <= 60:
            deps.db.update_session_title(session_id, clean_title)
    except Exception:
        pass


async def async_update_conversation_memory(session_id: str, model: str):
    """Progressively compact old turns without delaying the visible response."""
    lock = _memory_update_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        try:
            messages = deps.db.get_session_messages(session_id)
            memory = deps.db.get_session_memory(session_id)
            summarized_count = int(memory.get("summary_message_count", 0))
            profile = get_model_profile(model or settings.chat_model)
            if not should_compact(
                messages,
                summarized_count,
                profile.history_tokens,
            ):
                return

            compaction = compactable_head(
                messages,
                summarized_count,
                keep_recent=8,
            )
            reduced_messages = compaction["messages"]
            if not reduced_messages:
                return

            old_summary = str(memory.get("summary", "")).strip()
            summary_model = (
                settings.chat_model
                if "vl" in (model or "").lower() or "vision" in (model or "").lower()
                else (model or settings.chat_model)
            )
            reply = await asyncio.wait_for(
                deps.client.chat(
                    model=summary_model,
                    messages=build_compaction_messages(
                        old_summary,
                        reduced_messages,
                    ),
                    temperature=0.1,
                    think=False,
                    num_ctx=16_384,
                    num_predict=1_000,
                ),
                timeout=60.0,
            )
            updated_summary = reply.get("message", {}).get("content", "").strip()
            updated_summary = re.sub(
                r"<think>.*?</think>",
                "",
                updated_summary,
                flags=re.DOTALL,
            ).strip()
            if updated_summary:
                deps.db.update_session_memory(
                    session_id,
                    updated_summary[:3_600],
                    int(compaction["cutoff"]),
                )
        except Exception:
            # Memory compaction is an enhancement: a failure must never break chat.
            return


async def async_update_personal_memory(model: str):
    """Refresh cross-conversation preferences in one background job."""
    if _personal_memory_lock.locked():
        return
    async with _personal_memory_lock:
        try:
            await maybe_refresh_generated_memories(
                deps.db,
                deps.client,
                model or settings.chat_model,
            )
        except Exception:
            return
