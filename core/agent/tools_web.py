"""Outils agent web_research et web_read, branchés sur le client MCP."""

from __future__ import annotations

import re
from typing import Any

from core.agent.tools import CATEGORY_NETWORK, ToolDefinition, ToolRegistry
from core.mcp.research import read_pages, research_web
from core.mcp.types import McpClient

MAX_SEARCH_OUTPUT = 6_000
MAX_FETCH_TOTAL_CHARS = 14_000

_URL_RE = re.compile(r"https?://[^\s\)>\]\"']+")
_WARNING = (
    "⚠ Extraits insuffisants pour répondre : appelle web_read "
    "sur les URLs pertinentes avant de répondre."
)

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


class SearchResultNumbering:
    """Numérotation cumulative des résultats web d'un même message.

    Le modèle cite [n] et le frontend lit web_results[n-1]. Les numéros
    ne repartent pas à 1 entre deux recherches. ``seed`` réserve [1..N]
    pour une pré-recherche. « Aucun résultat. » n'alloue rien.
    """

    def __init__(self, start: int = 0) -> None:
        self._last = max(0, int(start))

    @property
    def last(self) -> int:
        return self._last

    def seed(self, start: int) -> None:
        self._last = max(self._last, int(start))

    def allocate(self, count: int) -> range:
        count = max(0, int(count))
        start = self._last + 1
        self._last += count
        return range(start, self._last + 1)


def pick_urls_for_reading(search_output: str, max_urls: int = 2) -> list[str]:
    """Choisit les URL les plus susceptibles de porter un résultat.

    Parse les blocs [titre / url indentée / extrait]. Le ton « résultat »
    passe devant le ton « pronostic » ; l'ordre d'origine départage.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in search_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("⚠"):
            continue
        if stripped.startswith(("Moteurs:", "Intention:")):
            continue
        header = re.match(r"^\[\d+\]\s+(.*)$", stripped)
        if header:
            if current:
                entries.append(current)
            current = {"title": header.group(1), "url": "", "snippet": ""}
            continue
        if current is None:
            continue
        if stripped.startswith(("http://", "https://")) and not current["url"]:
            current["url"] = stripped.rstrip(".,;")
        elif not current["snippet"]:
            current["snippet"] = stripped
    if current:
        entries.append(current)

    def score(entry: dict[str, str]) -> int:
        text = (entry["title"] + " " + entry["snippet"]).lower()
        value = sum(2 for marker in _RESULT_MARKERS if marker in text)
        value -= sum(3 for marker in _PREDICTION_MARKERS if marker in text)
        return value

    ranked = sorted(
        (entry for entry in entries if entry["url"]),
        key=lambda entry: (-score(entry), entries.index(entry)),
    )
    return [entry["url"] for entry in ranked[:max_urls]]


def collect_known_urls(events: list[dict[str, Any]]) -> set[str]:
    """URL vues par l'agent : résultats de recherche et pages lues."""
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
    """Retire les URL que l'agent n'a pas vues."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:")
        if url in known_urls:
            return match.group(0)
        trailing = match.group(0)[len(url):]
        return f"[source non vérifiée retirée]{trailing}"

    return _URL_RE.sub(_replace, text)


def _engine_header(payload: dict[str, Any], results: list[dict[str, Any]]) -> str:
    names: list[str] = []

    def add(raw: str) -> None:
        for part in re.split(r"[+·,]", raw):
            part = part.strip()
            if part and part not in names:
                names.append(part)

    engines = payload.get("engines")
    if isinstance(engines, str):
        add(engines)
    elif isinstance(engines, list):
        for item in engines:
            add(str(item))
    if not names:
        for result in results:
            add(str(result.get("engine") or ""))
    return " · ".join(names)


def _format_search_results(
    payload: dict[str, Any],
    numbering: SearchResultNumbering | None = None,
) -> str:
    """Liens bruts numérotés. L'avertissement web_read est unique, en fin."""
    results = [
        item
        for item in (payload.get("results") or [])
        if isinstance(item, dict)
        and str(item.get("url") or "").strip().startswith(("http://", "https://"))
    ]
    if not results:
        errors = payload.get("errors") or []
        if not isinstance(errors, list):
            errors = [errors]
        detail = (
            f" erreurs: {'; '.join(str(item) for item in errors[:2])}"
            if errors
            else ""
        )
        return f"Aucun résultat.{detail}"
    if numbering is None:
        numbering = SearchResultNumbering()
    numbers = numbering.allocate(len(results))
    lines: list[str] = []
    engines = _engine_header(payload, results)
    if engines:
        lines.append(f"Moteurs: {engines}")
    intent = str(payload.get("intent") or "").strip()
    if intent:
        lines.append(f"Intention: {intent}")
    for index, result in zip(numbers, results, strict=True):
        title = re.sub(r"\s+", " ", str(result.get("title") or "")).strip()
        title = (title or "Sans titre")[:140]
        url = str(result.get("url") or "").strip()
        snippet = re.sub(r"\s+", " ", str(result.get("snippet") or "")).strip()
        if len(snippet) > 500:
            snippet = snippet[:499].rstrip() + "…"
        lines.append(f"[{index}] {title}\n    {url}\n    {snippet}")
    body = "\n".join(lines)
    full = f"{body}\n{_WARNING}" if body else _WARNING
    if len(full) <= MAX_SEARCH_OUTPUT:
        return full
    keep = MAX_SEARCH_OUTPUT - len(_WARNING) - 1
    if keep < 1:
        return _WARNING[:MAX_SEARCH_OUTPUT]
    return f"{body[:keep].rstrip()}\n{_WARNING}"


def _resolve_mcp_client(mcp_client: McpClient | None) -> McpClient:
    if mcp_client is not None:
        return mcp_client
    from core.mcp.pool import get_mcp_client

    return get_mcp_client()


def register_web_tools(
    registry: ToolRegistry,
    *,
    mcp_client: McpClient | None = None,
    numbering: SearchResultNumbering | None = None,
) -> None:
    """Enregistre web_research et web_read. Le client absent est résolu à l'appel."""
    counter = numbering or SearchResultNumbering()
    registry.web_result_numbering = counter

    async def _research(args: dict[str, Any]) -> str:
        client = _resolve_mcp_client(mcp_client)
        recency = args.get("recency")
        payload = await research_web(
            client,
            str(args["query"]).strip(),
            recency=None if recency in (None, "", "any") else str(recency),
            intent=str(args.get("intent") or "auto"),
            max_results=8,
        )
        return _format_search_results(payload, counter)

    async def _read(args: dict[str, Any]) -> str:
        client = _resolve_mcp_client(mcp_client)
        raw_urls = args.get("urls") or []
        if isinstance(raw_urls, str):
            raw_urls = [raw_urls]
        return await read_pages(client, [str(url) for url in raw_urls])

    registry.register(
        ToolDefinition(
            name="web_research",
            description=(
                "Interroge plusieurs moteurs MCP (Exa, Brave, Tavily) plus "
                "une source spécialisée selon le sujet (sport, météo, actu, "
                "wikipedia, arxiv, HN). Ne renvoie que des liens bruts "
                "numérotés (titre, URL, extrait), jamais une réponse rédigée. "
                "La numérotation est cumulative entre les appels du même "
                "message. Avant de citer, appelle web_read sur les URLs "
                "pertinentes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Requête de recherche",
                    },
                    "recency": {
                        "type": "string",
                        "enum": ["any", "hour", "day", "week", "month", "year"],
                        "description": "Fenêtre de fraîcheur souhaitée",
                    },
                    "intent": {
                        "type": "string",
                        "enum": [
                            "auto",
                            "general",
                            "news",
                            "sports",
                            "weather",
                            "academic",
                            "knowledge",
                            "code",
                            "finance",
                        ],
                        "description": "auto déduit le sujet, sinon force le routage",
                    },
                },
                "required": ["query"],
            },
            handler=_research,
            category=CATEGORY_NETWORK,
            timeout_s=90.0,
            max_output_chars=MAX_SEARCH_OUTPUT,
        )
    )
    registry.register(
        ToolDefinition(
            name="web_read",
            description=(
                "Lit le contenu de 1 à 5 pages web. À appeler AVANT de citer : "
                "la réponse doit s'appuyer sur des pages réellement lues, pas "
                "seulement sur les extraits de web_research."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs http(s) à lire (1 à 5)",
                    }
                },
                "required": ["urls"],
            },
            handler=_read,
            category=CATEGORY_NETWORK,
            timeout_s=120.0,
            max_output_chars=MAX_FETCH_TOTAL_CHARS,
        )
    )
