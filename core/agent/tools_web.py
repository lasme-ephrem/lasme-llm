"""Agent tools for web search and page fetching.

Design (Phase 3, informed by the tinyfish/Monid study):
- one ``web_search`` tool with an explicit ``recency`` window (down to
  the last hour) instead of hidden freshness heuristics;
- one ``fetch_pages`` tool that takes a *batch* of URLs and returns
  model-ready markdown;
- the proven v1 chain (Sonar → specialists → SearXNG → Brave → Tavily →
  DDG, adaptive stop, dedup, ranking) stays the engine — wrapped, not
  rewritten. An alternate engine (e.g. tinyfish via Monid) can be
  injected at registry build time without touching the tool contract.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

from core.agent.tools import (
    CATEGORY_NETWORK,
    CATEGORY_READ,
    ToolDefinition,
    ToolRegistry,
)

RECENCY_HINTS = {
    "hour": " (dernière heure)",
    "day": " (dernières 24 heures)",
    "week": " (dernière semaine)",
    "month": " (dernier mois)",
    "year": " (dernière année)",
}

MAX_SEARCH_OUTPUT = 6_000
MAX_FETCH_URLS = 5
MAX_FETCH_TOTAL_CHARS = 14_000


def _format_search_results(payload: Dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not results:
        errors = payload.get("errors") or []
        detail = f" erreurs: {'; '.join(errors[:2])}" if errors else ""
        return f"Aucun résultat.{detail}"
    lines = [f"Moteur : {payload.get('engine') or 'multi'}"]
    for index, result in enumerate(results, start=1):
        title = str(result.get("title") or "Sans titre").strip()[:140]
        url = str(result.get("url") or "").strip()
        snippet = str(result.get("snippet") or "").strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        lines.append(f"[{index}] {title}\n    {url}\n    {snippet}")
    return "\n".join(lines)[:MAX_SEARCH_OUTPUT]


async def _run_web_search(
    search_fn: Callable[..., Dict[str, Any]],
    args: Dict[str, Any],
) -> str:
    query = str(args["query"]).strip()
    recency = str(args.get("recency") or "any")
    if recency in RECENCY_HINTS:
        query += RECENCY_HINTS[recency]
    max_results = int(args.get("max_results") or 5)
    payload = await asyncio.to_thread(
        search_fn, query, max_results, None, force_full_chain=(recency != "any")
    )
    return _format_search_results(payload)


async def _run_fetch_pages(
    fetch_fn: Callable[[str], str],
    args: Dict[str, Any],
) -> str:
    urls = [str(u).strip() for u in args["urls"] if str(u).strip()]
    sections: List[str] = []
    budget = MAX_FETCH_TOTAL_CHARS

    async def fetch_one(url: str) -> tuple[str, str]:
        try:
            text = await asyncio.to_thread(fetch_fn, url)
            return url, text or ""
        except Exception as exc:  # network failures are per-URL facts
            return url, f"ERREUR: {type(exc).__name__}: {exc}"

    for url, text in await asyncio.gather(*(fetch_one(u) for u in urls)):
        if text.startswith("ERREUR"):
            sections.append(f"## {url}\n{text}")
            continue
        allowance = max(1_500, budget // max(1, len(urls)))
        if len(text) > allowance:
            text = text[:allowance] + f"\n…[tronqué à {allowance} caractères]"
        budget -= len(text)
        sections.append(f"## {url} ({len(text)} caractères)\n{text}")
    return "\n\n".join(sections)[:MAX_FETCH_TOTAL_CHARS]


def register_web_tools(
    registry: ToolRegistry,
    *,
    search_fn: Callable[..., Dict[str, Any]],
    fetch_fn: Callable[[str], str],
) -> None:
    registry.register(
        ToolDefinition(
            name="web_search",
            description=(
                "Recherche sur le Web et retourne des sources numérotées "
                "(titre, URL, extrait). Utilise 'recency' pour une fenêtre "
                "de fraîcheur (jusqu'à la dernière heure)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Recherche"},
                    "max_results": {
                        "type": "integer",
                        "description": "Nombre de sources (1-8)",
                        "enum": [1, 2, 3, 4, 5, 6, 7, 8],
                    },
                    "recency": {
                        "type": "string",
                        "enum": ["any", "hour", "day", "week", "month", "year"],
                        "description": "Fenêtre de fraîcheur souhaitée",
                    },
                },
                "required": ["query"],
            },
            handler=lambda args: _run_web_search(search_fn, args),
            category=CATEGORY_NETWORK,
            timeout_s=90.0,
            max_output_chars=MAX_SEARCH_OUTPUT,
        )
    )
    registry.register(
        ToolDefinition(
            name="fetch_pages",
            description=(
                "Récupère le contenu de 1 à 5 URLs en Markdown prêt à "
                "l'analyse. À utiliser après web_search pour lire les "
                "sources prometteuses."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs à récupérer",
                    }
                },
                "required": ["urls"],
            },
            handler=lambda args: _run_fetch_pages(fetch_fn, args),
            category=CATEGORY_NETWORK,
            timeout_s=120.0,
            max_output_chars=MAX_FETCH_TOTAL_CHARS,
        )
    )
