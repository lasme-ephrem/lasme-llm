from __future__ import annotations

import re
from typing import Any, Dict, List


def estimate_text_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(
        estimate_text_tokens(str(message.get("content", ""))) + 6
        for message in messages
    )


def _strip_old_reference_payload(content: str) -> str:
    text = re.sub(
        r"(?is)\n*#{1,3}\s*(?:sources|références|references)\b[\s\S]*$",
        "",
        content or "",
    )
    text = re.sub(
        r"(?is)<(?:source|document)\b[^>]*>[\s\S]*?</(?:source|document)>",
        "[ancien résultat externe retiré]",
        text,
    )
    return text.strip()


def compactable_head(
    messages: List[Dict[str, Any]],
    summarized_count: int,
    keep_recent: int = 8,
) -> Dict[str, Any]:
    cutoff = max(0, len(messages) - keep_recent)
    fresh_head = messages[max(0, summarized_count) : cutoff]
    reduced: List[Dict[str, str]] = []
    removed_chars = 0
    for message in fresh_head:
        original = str(message.get("content", ""))
        cleaned = _strip_old_reference_payload(original)
        limit = 1_800 if message.get("role") == "user" else 1_400
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip() + " […]"
        removed_chars += max(0, len(original) - len(cleaned))
        if cleaned:
            reduced.append(
                {
                    "role": str(message.get("role", "user")),
                    "content": cleaned,
                }
            )
    return {
        "messages": reduced,
        "cutoff": cutoff,
        "removed_chars": removed_chars,
        "original_count": len(fresh_head),
    }


def should_compact(
    messages: List[Dict[str, Any]],
    summarized_count: int,
    history_budget: int,
) -> bool:
    unsummarized = messages[max(0, summarized_count) :]
    if len(unsummarized) < 8:
        return False
    return (
        estimate_messages_tokens(unsummarized) >= int(history_budget * 0.62)
        or len(unsummarized) >= 14
    )


def build_compaction_messages(
    old_summary: str,
    reduced_messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    transcript = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in reduced_messages
    )
    return [
        {
            "role": "system",
            "content": (
                "Tu compactes une conversation sans la poursuivre. Produis uniquement "
                "un compte rendu dense et fidèle avec, lorsque pertinent : objectif "
                "principal, faits et décisions, personnes/projets/fichiers, erreurs et "
                "corrections, état actuel et travail restant. Préserve les noms, dates, "
                "nombres, contraintes et décisions importantes. Ne conserve pas les "
                "anciens extraits Web ou documents verbatim : garde seulement les "
                "conclusions établies et leur degré de certitude. N'invente rien."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Contexte compacté précédent :\n{old_summary or '(aucun)'}\n\n"
                f"Nouveaux échanges à intégrer :\n{transcript}"
            ),
        },
    ]

