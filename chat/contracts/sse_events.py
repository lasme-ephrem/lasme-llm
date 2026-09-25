"""Contrat SSE du chat — événements typés et versionnés (v2).

Source de vérité frontend/backend du flux ``POST /api/chat/stream`` :

| Événement          | Champ texte | Sémantique                                  |
|--------------------|-------------|---------------------------------------------|
| ``session``        | —           | contexte (ids, web, context_meta)           |
| ``reasoning_start``| —           | début de réflexion                          |
| ``reasoning_delta``| ``text``    | incrément de réflexion                      |
| ``reasoning_done`` | —           | fin de réflexion (+ duration)               |
| ``content_delta``  | ``content`` | texte PROVISOIRE, diffusé en direct         |
| ``content_reset``  | ``text``    | ce texte n'était pas la réponse → rangé en  |
|                    |             | note de travail (reason: tool_call,         |
|                    |             | fetch_required_before_answer,               |
|                    |             | search_required_by_request, budget_retried) |
| ``content_replace``| ``text``    | version assainie = texte persisté           |
| ``agent_tool_call``| —           | appel d'outil (id, name, arguments)         |
| ``agent_tool_result``| —         | résultat d'outil (ok, output, error…)       |
| ``web_search_done``| —           | sources découvertes par l'agent             |
| ``generation_stats``| —          | tok/s, TTFT, durées                         |
| ``message_saved``  | —           | persistance (message_id)                    |
| ``[DONE]``         | —           | fin de flux                                 |

Règle d'or UX : **jamais de texte affiché puis supprimé** — un texte
écarté est rangé (``content_reset``), la réponse finale seule occupe la
zone de réponse.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Set

SSE_VERSION = 2

# Types d'événements du contrat (le test de contrat vérifie que chaque
# événement émis par les modules appartient bien à cet ensemble).
EVENT_TYPES: Set[str] = {
    "session",
    "reasoning_start",
    "reasoning_delta",
    "reasoning_done",
    "content_delta",
    "content_reset",
    "content_replace",
    "agent_tool_call",
    "agent_tool_result",
    "web_search_done",
    "generation_stats",
    "message_saved",
    "error",
    # Recherche approfondie
    "research_plan",
    "research_step",
    "research_synthesis",
    "research_done",
    # Images
    "image_start",
    "image_done",
}

# Raisons possibles de content_reset (rangement d'un brouillon).
RESET_REASONS: Set[str] = {
    "tool_call",
    "fetch_required_before_answer",
    "search_required_by_request",
    "budget_retried",
}

DONE_FRAME = "data: [DONE]\n\n"


def sse_frame(payload: Dict[str, Any]) -> str:
    """Encodage d'un événement en frame SSE."""
    return f"data: {json.dumps(payload)}\n\n"


def content_delta(content: str) -> str:
    return sse_frame({"type": "content_delta", "content": content})


def content_reset(text: str, reason: str) -> str:
    if reason not in RESET_REASONS:
        raise ValueError(f"Unknown content_reset reason: {reason}")
    return sse_frame({"type": "content_reset", "text": text, "reason": reason})


def content_replace(text: str) -> str:
    return sse_frame({"type": "content_replace", "text": text})


def iter_event_types(frames: Iterable[str]) -> Set[str]:
    """Outil de test : types d'événements présents dans une série de frames."""
    types: Set[str] = set()
    for frame in frames or []:
        line = frame.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            payload = json.loads(line[len("data: "):])
        except Exception:
            continue
        event_type = payload.get("type")
        if event_type:
            types.add(str(event_type))
    return types
