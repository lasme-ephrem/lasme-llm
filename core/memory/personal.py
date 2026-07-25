from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Iterable, List


AUTO_SAVE_INTERVAL = 10
MAX_MEMORY_ITEMS = 40
_SENSITIVE_MEMORY_PATTERNS = (
    re.compile(
        r"\b(password|mot de passe|secret|api[_ -]?key|access[_ -]?token|"
        r"bearer|private key|clé privée|seed phrase)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
)


def format_personal_memory_context(
    settings: Dict[str, Any],
    memories: Iterable[Dict[str, Any]],
) -> str:
    if not settings.get("enabled", True):
        return ""
    active = [
        " ".join(str(item.get("content", "")).split()).strip()
        for item in memories
        if item.get("enabled", True)
    ]
    active = [item for item in active if item]
    if not active:
        return ""
    lines = "\n".join(f"- {item}" for item in active[:MAX_MEMORY_ITEMS])
    return (
        "Préférences et informations durables explicitement mémorisées. "
        "Utilise-les seulement lorsqu'elles sont pertinentes et ne les mentionne "
        f"pas comme une base de données interne :\n{lines}"
    )


def parse_memory_array(raw: str) -> List[str]:
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL)
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    results: List[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        normalized = " ".join(item.split()).strip()[:300]
        key = normalized.casefold()
        if len(normalized) < 8 or key in seen:
            continue
        seen.add(key)
        results.append(normalized)
        if len(results) >= MAX_MEMORY_ITEMS:
            break
    return results


def is_safe_generated_memory(value: str) -> bool:
    """Reject likely credentials even if the local model ignored its prompt."""
    text = value or ""
    return not any(pattern.search(text) for pattern in _SENSITIVE_MEMORY_PATTERNS)


def build_memory_refresh_prompt(
    prompts: List[str],
    existing_memories: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    existing = "\n".join(
        f"- {item.get('content', '')}"
        for item in existing_memories
        if item.get("content")
    ) or "(aucune)"
    samples = "\n".join(f"{index + 1}. {value}" for index, value in enumerate(prompts))
    return [
        {
            "role": "system",
            "content": (
                "Tu extrais une mémoire personnelle durable pour un assistant. "
                "Analyse les demandes comme un ensemble et conserve uniquement les "
                "préférences stables, langues, outils récurrents, domaines de travail, "
                "projets durables et contraintes utiles. Exclue les tâches ponctuelles, "
                "les faits généraux, les mots de passe, jetons, coordonnées, identifiants "
                "et données sensibles. N'invente rien. Déduplique sémantiquement. "
                "Réponds uniquement avec un tableau JSON de chaînes autonomes, chacune "
                "de 300 caractères maximum. Retourne [] si aucun signal durable n'existe."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Mémoires existantes à ne pas dupliquer :\n{existing}\n\n"
                f"Échantillon récent des demandes utilisateur :\n{samples}"
            ),
        },
    ]


async def refresh_generated_memories(database, inference_client, model: str) -> int:
    settings = database.get_memory_settings()
    if not settings.get("enabled", True) or not settings.get("auto_save", True):
        return 0
    prompts = database.list_recent_user_prompts(limit=100)
    if len(prompts) < 4:
        return 0
    existing = database.list_personal_memories()
    response = await asyncio.wait_for(
        inference_client.chat(
            model=model,
            messages=build_memory_refresh_prompt(prompts, existing),
            temperature=0.0,
            think=False,
            num_ctx=8_192,
            num_predict=900,
        ),
        timeout=60.0,
    )
    memories = [
        item
        for item in parse_memory_array(
            response.get("message", {}).get("content", "")
        )
        if is_safe_generated_memory(item)
    ]
    if memories:
        database.replace_generated_memories(memories)
    return len(memories)


async def maybe_refresh_generated_memories(
    database,
    inference_client,
    model: str,
) -> int:
    settings = database.get_memory_settings()
    if not settings.get("enabled", True) or not settings.get("auto_save", True):
        return 0
    counter = int(settings.get("prompt_counter", 0)) + 1
    if counter < AUTO_SAVE_INTERVAL:
        database.update_memory_settings(prompt_counter=counter)
        return 0
    database.update_memory_settings(prompt_counter=0)
    return await refresh_generated_memories(database, inference_client, model)
