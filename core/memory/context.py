import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set


_STOP_WORDS = {
    "alors",
    "avec",
    "avoir",
    "cette",
    "comme",
    "dans",
    "donc",
    "elle",
    "elles",
    "encore",
    "entre",
    "être",
    "faire",
    "mais",
    "nous",
    "pour",
    "plus",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "sans",
    "sont",
    "tout",
    "tous",
    "très",
    "vous",
}


@dataclass
class ContextSelection:
    messages: List[Dict[str, Any]]
    original_message_count: int
    selected_message_count: int
    estimated_tokens: int
    summary_used: bool


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate suitable for local GGUF models."""
    return max(1, math.ceil(len(text) / 3.5))


def _content_tokens(text: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9_-]{3,}", text.lower())
        if token not in _STOP_WORDS
    }


def _message_cost(message: Dict[str, Any]) -> int:
    content = str(message.get("content", ""))
    image_cost = 700 if message.get("images") else 0
    return estimate_tokens(content) + image_cost + 8


def _relevance_score(message: Dict[str, Any], query_tokens: Set[str]) -> float:
    if not query_tokens:
        return 0.0
    message_tokens = _content_tokens(str(message.get("content", "")))
    overlap = query_tokens.intersection(message_tokens)
    if not overlap:
        return 0.0
    return len(overlap) / max(1, len(query_tokens))


def select_conversation_context(
    messages: Sequence[Dict[str, Any]],
    latest_query: str,
    summary: str = "",
    max_history_tokens: int = 4200,
    recent_message_limit: int = 10,
    relevant_message_limit: int = 4,
) -> ContextSelection:
    """
    Keep the latest turns plus a few relevant older messages within a token budget.

    Messages remain in chronological order so pronouns, corrections and follow-ups
    retain their natural conversational meaning.
    """
    normalized = [
        dict(message)
        for message in messages
        if message.get("role") in {"user", "assistant"} and message.get("content")
    ]
    if not normalized:
        return ContextSelection([], 0, 0, 0, bool(summary.strip()))

    recent_start = max(0, len(normalized) - recent_message_limit)
    selected_indices = set(range(recent_start, len(normalized)))
    query_tokens = _content_tokens(latest_query)
    summary_text = summary.strip()
    summary_message = None
    summary_cost = 0
    if summary_text:
        summary_message = {
            "role": "system",
            "content": (
                "Mémoire condensée des échanges plus anciens — utilise-la comme "
                "contexte, sans la citer ni prétendre qu'elle est un nouveau message :\n"
                f"{summary_text}"
            ),
        }
        summary_cost = _message_cost(summary_message)
    history_budget = max(256, max_history_tokens - summary_cost)

    older_scores = sorted(
        (
            (_relevance_score(message, query_tokens), index)
            for index, message in enumerate(normalized[:recent_start])
        ),
        reverse=True,
    )
    relevant_added = 0
    for score, index in older_scores:
        if score <= 0 or relevant_added >= relevant_message_limit:
            break
        selected_indices.add(index)
        # Keep the adjacent message so a recalled answer retains its question,
        # and a recalled question retains the answer that followed it.
        neighbor = index - 1 if normalized[index]["role"] == "assistant" else index + 1
        if 0 <= neighbor < recent_start:
            selected_indices.add(neighbor)
        relevant_added += 1

    # Always keep the newest user message, then spend the remaining budget from
    # newest to oldest so recent conversational continuity wins.
    kept: List[int] = []
    used_tokens = 0
    for index in sorted(selected_indices, reverse=True):
        cost = _message_cost(normalized[index])
        if kept and used_tokens + cost > history_budget:
            continue
        kept.append(index)
        used_tokens += cost

    kept.sort()
    selected_messages = [normalized[index] for index in kept]
    if summary_message:
        selected_messages.insert(0, summary_message)
        used_tokens += summary_cost

    return ContextSelection(
        messages=selected_messages,
        original_message_count=len(normalized),
        selected_message_count=len(selected_messages),
        estimated_tokens=used_tokens,
        summary_used=bool(summary_text),
    )
