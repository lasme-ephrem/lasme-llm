"""Agent tools for web search and page fetching — fully agentic.

Design (W phases):
- NO provider synthesis: Perplexity Sonar is never called by the agent;
  the search tool returns RAW ranked links and OUR model does the
  reading, comparing and citing through ``fetch_pages``.
- Provider chain (all link providers, no Docker): Monid (tinyfish, if
  MONID_API_KEY is set) → DuckDuckGo → specialists (GDELT/OpenAlex/
  Wikimedia) → Brave → Tavily. The proven ranking (dedup, authority,
  freshness, MMR) is reused. Monid lives inside the chain itself
  (first provider, automatic fallback), not as a pre-chain shortcut.
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

# Stale-index triage: search engines mix pre-event prediction/betting
# pages with post-event result pages. When the harness auto-fetches,
# result-toned pages must be read first.
_RESULT_MARKERS = (
    "s'est terminé", "s'est imposé", "champion", "sacré", "a remporté",
    "vainqueur", "a battu", "victoire", "classement final",
    "a gagné", "couronné", "s'est conclu", "résultat",
)
_PREDICTION_MARKERS = (
    "pronostic", "cote", "parier", "bookmaker", "favori",
    "se déroulera", "aura lieu", "à venir", "prévu", "prédiction",
    "sondage", "prédire",
)


def pick_urls_for_reading(search_output: str, max_urls: int = 2) -> List[str]:
    """Pick the URLs most likely to carry *results*, not predictions.

    Parses the numbered [title / url / snippet] blocks produced by
    ``_format_search_results`` and ranks them: result-toned text wins,
    prediction-toned text sinks, original order breaks ties.
    """
    entries: List[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    for line in search_output.splitlines():
        stripped = line.strip()
        header = re.match(r"^\[\d+\]\s+(.*)$", stripped)
        if header:
            if current:
                entries.append(current)
            current = {"title": header.group(1), "url": "", "snippet": ""}
        elif current is not None:
            if stripped.startswith("http"):
                current["url"] = stripped
            elif stripped and not current["snippet"]:
                current["snippet"] = stripped
    if current:
        entries.append(current)

    def score(entry: Dict[str, str]) -> int:
        text = (entry["title"] + " " + entry["snippet"]).lower()
        value = sum(2 for marker in _RESULT_MARKERS if marker in text)
        value -= sum(3 for marker in _PREDICTION_MARKERS if marker in text)
        return value

    ranked = sorted(
        (entry for entry in entries if entry["url"]),
        key=lambda entry: (-score(entry), entries.index(entry)),
    )
    return [entry["url"] for entry in ranked[:max_urls]]


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
        lines.append(
            "⚠ Extraits insuffisants pour répondre : appelle fetch_pages "
            "sur les URLs pertinentes avant de répondre."
        )
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
    # Monid (if configured) is tried inside the chain itself, as its first
    # provider, with automatic fallback to the local providers.
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
