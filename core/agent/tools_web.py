"""Agent tools for web search and page fetching — fully agentic.

Design (W phases):
- NO provider synthesis: Perplexity Sonar is never called by the agent;
  the search tool returns RAW ranked links and OUR model does the
  reading, comparing and citing through ``fetch_pages``.
- Provider chain (all link providers, no Docker): DuckDuckGo →
  specialists (GDELT/OpenAlex/Wikimedia) → Brave → Tavily. The proven
  ranking (dedup, authority, freshness, MMR) is reused. An alternate
  link provider (tinyfish via Monid, if MONID_API_KEY is set) plugs in
  ahead of the chain through the same contract.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Dict, List, Match

from core.agent.tools import (
    CATEGORY_NETWORK,
    CATEGORY_READ,
    ToolDefinition,
    ToolRegistry,
)
from core.tools import monid_provider

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

_URL_RE = re.compile(r"https?://[^\s\)>\]\"']+")


def collect_known_urls(events: List[Dict[str, Any]]) -> set[str]:
    """URLs legitimately seen by the agent: search results + fetched pages.

    Accepts the serialized event list of a run (see EventLog.to_list()).
    """
    known: set[str] = set()
    for event in events:
        if event.get("type") not in ("tool_call", "tool_result"):
            continue
        haystack = " ".join(
            str(event.get(key) or "")
            for key in ("arguments", "output")
        )
        for match in _URL_RE.findall(haystack):
            known.add(match.rstrip(".,;:"))
    return known


def strip_unsupported_citations(text: str, known_urls: set[str]) -> str:
    """Remove URLs the agent never actually saw (anti-hallucination).

    Markdown links lose only their target; bare URLs are replaced by a
    short marker so the sentence stays readable.
    """

    def _replace(match: Match[str]) -> str:
        url = match.group(0).rstrip(".,;:")
        if url in known_urls:
            return match.group(0)
        trailing = match.group(0)[len(url):]
        return f"[source non vérifiée retirée]{trailing}"

    return _URL_RE.sub(_replace, text)


def _format_search_results(payload: Dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not results:
        errors = payload.get("errors") or []
        detail = f" erreurs: {'; '.join(errors[:2])}" if errors else ""
        return f"Aucun résultat.{detail}"
    lines = []
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

    # Agentic rule: link providers only — never a synthesizing provider.
    payload: Dict[str, Any] | None = None
    if monid_provider.is_available():
        try:
            links = await monid_provider.search_links(query, max_results)
            if links:
                payload = {"results": links, "errors": [], "engine": "tinyfish/Monid"}
        except Exception:
            payload = None  # fall through to the local chain
    if payload is None:
        payload = await asyncio.to_thread(
            search_fn,
            query,
            max_results,
            None,
            skip_primary_provider=True,
            force_full_chain=(recency != "any"),
        )
        payload.pop("provider_answer", None)
        payload.pop("answer_mode", None)
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
                "Recherche sur le Web et retourne des LIENS BRUTS "
                "numérotés (titre, URL, extrait) — jamais de réponse "
                "pré-rédigée. 'recency' filtre la fraîcheur (jusqu'à la "
                "dernière heure). RÈGLE : pour toute information issue de "
                "cette recherche, appelle ensuite fetch_pages sur les URLs "
                "pertinentes et ne cite que ce que tu y as lu."
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
                "Récupère le contenu intégral de 1 à 5 URLs en Markdown. "
                "À utiliser après web_search AVANT de répondre : ta "
                "synthèse et tes citations doivent provenir de pages que "
                "tu as réellement lues."
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
