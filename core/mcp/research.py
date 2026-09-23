"""Fan-out de recherche et lecture de pages, uniquement via McpClient."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from core.mcp.intent import INTENT_LABELS, classify_intent, is_tech_news
from core.mcp.merge import SearchHit, merge_hits, parse_mcp_payload
from core.mcp.types import (
    SERVER_ARXIV,
    SERVER_BRAVE,
    SERVER_EXA,
    SERVER_FETCH,
    SERVER_FRESHNESS,
    SERVER_TAVILY,
    TOOL_ARXIV_SEARCH,
    TOOL_BRAVE_NEWS,
    TOOL_BRAVE_WEB,
    TOOL_EXA_FETCH,
    TOOL_EXA_SEARCH,
    TOOL_FETCH,
    TOOL_SPORTS,
    TOOL_TAVILY_EXTRACT,
    TOOL_TAVILY_SEARCH,
    TOOL_TECH_NEWS,
    TOOL_WEATHER,
    TOOL_WIKI,
    McpClient,
)

_SEARCH_TIMEOUT_S = 25.0
_READ_TIMEOUT_S = 25.0
_PAGE_BUDGET = 14_000
_PAGE_MIN = 1_500
_USEFUL = 200
_MAX_URLS = 5

_BRAVE_FRESHNESS = {
    "hour": "pd",
    "day": "pd",
    "week": "pw",
    "month": "pm",
    "year": "py",
}
_RECENCY = {"hour", "day", "week", "month", "year"}
_LABEL_TO_INTENT = {label.lower(): key for key, label in INTENT_LABELS.items()}


@dataclass(frozen=True)
class _Job:
    server: str
    tool: str
    engine: str
    attempts: tuple[dict[str, Any], ...]


def _clean_query(query: str) -> str:
    return " ".join(str(query or "").split())


def _clean_recency(recency: str | None) -> str | None:
    if recency is None:
        return None
    value = str(recency).strip().lower()
    if value in {"", "any", "none"}:
        return None
    if value in _RECENCY:
        return value
    return None


def _resolve_intent(query: str, intent: str | None) -> str:
    value = str(intent or "auto").strip().lower()
    if value in {"", "auto"}:
        return classify_intent(query)
    if value in INTENT_LABELS:
        return value
    mapped = _LABEL_TO_INTENT.get(value)
    if mapped:
        return mapped
    return classify_intent(query)


def _tavily_range(recency: str | None) -> str | None:
    if recency == "hour":
        return "day"
    if recency in {"day", "week", "month", "year"}:
        return recency
    return None


def _remote_count(max_results: int) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        return 8
    return min(8, max(6, value))


def _result_limit(max_results: int) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        return 8
    return value if value > 0 else 8


def _attempts(query: str, full: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Args complets, puis sans filtres, puis ``{"query"}`` seul."""
    slim = {
        key: value
        for key, value in full.items()
        if key not in {"freshness", "time_range", "topic", "place"}
    }
    attempts: list[dict[str, Any]] = []
    for candidate in (full, slim, {"query": query}):
        if not candidate or candidate in attempts:
            continue
        attempts.append(dict(candidate))
    return tuple(attempts)


def _jobs(query: str, intent: str, recency: str | None, size: int) -> list[_Job]:
    brave_fresh = _BRAVE_FRESHNESS.get(recency or "")
    tavily_range = _tavily_range(recency)

    def brave(tool: str, fresh: str | None) -> _Job:
        payload: dict[str, Any] = {"query": query, "count": size}
        if fresh:
            payload["freshness"] = fresh
        return _Job(SERVER_BRAVE, tool, "brave", _attempts(query, payload))

    def tavily(topic: str) -> _Job:
        payload: dict[str, Any] = {
            "query": query,
            "max_results": size,
            "topic": topic,
        }
        if tavily_range:
            payload["time_range"] = tavily_range
        return _Job(
            SERVER_TAVILY, TOOL_TAVILY_SEARCH, "tavily", _attempts(query, payload)
        )

    exa = _Job(
        SERVER_EXA,
        TOOL_EXA_SEARCH,
        "exa",
        _attempts(query, {"query": query, "numResults": size}),
    )
    arxiv = _Job(
        SERVER_ARXIV,
        TOOL_ARXIV_SEARCH,
        "arxiv",
        _attempts(query, {"query": query, "max_results": size}),
    )
    if intent == "weather":
        return [
            _Job(
                SERVER_FRESHNESS,
                TOOL_WEATHER,
                "weather",
                _attempts(query, {"place": query}),
            ),
            brave(TOOL_BRAVE_WEB, brave_fresh),
        ]
    if intent == "sports":
        return [
            _Job(
                SERVER_FRESHNESS,
                TOOL_SPORTS,
                "sports",
                _attempts(query, {"query": query}),
            ),
            brave(TOOL_BRAVE_NEWS, brave_fresh or "pd"),
            exa,
            tavily("news"),
        ]
    if intent == "academic":
        return [arxiv, exa]
    if intent == "knowledge":
        return [
            _Job(
                SERVER_FRESHNESS,
                TOOL_WIKI,
                "wikipedia",
                _attempts(query, {"query": query}),
            ),
            exa,
        ]
    if intent == "code":
        # Le serveur Exa stdio n'active pas get_code_context_exa par défaut.
        return [exa, tavily("general")]
    if intent == "news":
        planned = [brave(TOOL_BRAVE_NEWS, brave_fresh), tavily("news"), exa]
        if is_tech_news(query):
            planned.append(
                _Job(
                    SERVER_FRESHNESS,
                    TOOL_TECH_NEWS,
                    "hackernews",
                    _attempts(query, {"query": query}),
                )
            )
        return planned
    if intent == "finance":
        return [exa, brave(TOOL_BRAVE_WEB, brave_fresh or "pd"), tavily("general")]
    return [exa, brave(TOOL_BRAVE_WEB, brave_fresh), tavily("general")]


async def _run_job(
    client: McpClient, job: _Job
) -> tuple[list[SearchHit], str | None]:
    try:
        if not client.available(job.server):
            return [], None
    except Exception as exc:
        return [], f"{job.server}.{job.tool}: {type(exc).__name__}: {exc}"
    last_error = "échec"
    try:
        for args in job.attempts:
            result = await client.call(
                job.server,
                job.tool,
                dict(args),
                timeout_s=_SEARCH_TIMEOUT_S,
            )
            if result.ok:
                return parse_mcp_payload(result.text, job.engine), None
            if result.error:
                last_error = result.error
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
    return [], f"{job.server}.{job.tool}: {last_error}"


def _engines_used(jobs: list[_Job], hits: list[SearchHit]) -> list[str]:
    used = {
        part
        for hit in hits
        for part in (hit.engine or "").split("+")
        if part
    }
    names: list[str] = []
    for job in jobs:
        if job.engine in used and job.engine not in names:
            names.append(job.engine)
    for hit in hits:
        for part in (hit.engine or "").split("+"):
            if part and part not in names:
                names.append(part)
    return names


async def research_web(
    client: McpClient,
    query: str,
    *,
    recency: str | None = None,
    intent: str = "auto",
    max_results: int = 8,
) -> dict[str, Any]:
    """Fan-out MCP. Une panne n'annule pas les autres moteurs."""
    cleaned = _clean_query(query)
    window = _clean_recency(recency)
    resolved = _resolve_intent(cleaned, intent)
    jobs = _jobs(cleaned, resolved, window, _remote_count(max_results))
    outcomes = await asyncio.gather(
        *(_run_job(client, job) for job in jobs),
        return_exceptions=True,
    )
    groups: list[list[SearchHit]] = []
    errors: list[str] = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            errors.append(f"{type(outcome).__name__}: {outcome}")
            groups.append([])
            continue
        hits, error = outcome
        groups.append(hits)
        if error:
            errors.append(error)
    merged = merge_hits(groups, cleaned, resolved, limit=_result_limit(max_results))
    results = [
        {
            "title": hit.title,
            "url": hit.url,
            "snippet": hit.snippet,
            "engine": hit.engine,
        }
        for hit in merged
    ]
    return {
        "results": results,
        "engines": _engines_used(jobs, merged),
        "intent": INTENT_LABELS.get(resolved, "général"),
        "errors": errors,
    }


def _select_urls(urls: list[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        selected.append(url)
        if len(selected) >= _MAX_URLS:
            break
    return selected


def _one_line(text: str, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _payload_text(raw: str) -> str:
    stripped = (raw or "").strip()
    if not stripped:
        return ""
    if stripped[0] not in "[{":
        return stripped
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    extracted = _extract_text(data).strip()
    return extracted or stripped


def _extract_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        parts = [_extract_text(item) for item in data]
        return "\n\n".join(part for part in parts if part)
    if isinstance(data, dict):
        best = ""
        for key in (
            "text",
            "content",
            "markdown",
            "extract",
            "body",
            "raw_content",
        ):
            value = data.get(key)
            if isinstance(value, str) and len(value.strip()) > len(best):
                best = value.strip()
        for value in data.values():
            if isinstance(value, (dict, list)):
                nested = _extract_text(value)
                if len(nested) > len(best):
                    best = nested
        return best
    return ""


async def _try_read(
    client: McpClient, server: str, tool: str, args: dict[str, Any]
) -> tuple[bool, str, str]:
    try:
        result = await client.call(
            server, tool, dict(args), timeout_s=_READ_TIMEOUT_S
        )
    except Exception as exc:
        return False, "", f"{type(exc).__name__}: {exc}"
    if not result.ok:
        return False, "", result.error or "échec"
    return True, _payload_text(result.text), ""


async def _read_one(client: McpClient, url: str) -> tuple[str, str]:
    attempts: list[tuple[str, str, dict[str, Any]]] = []
    try:
        exa_up = client.available(SERVER_EXA)
        tavily_up = client.available(SERVER_TAVILY)
        fetch_up = client.available(SERVER_FETCH)
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"
    if exa_up:
        attempts.append((SERVER_EXA, TOOL_EXA_FETCH, {"urls": [url]}))
        attempts.append((SERVER_EXA, TOOL_EXA_FETCH, {"url": url}))
    if tavily_up:
        attempts.append((SERVER_TAVILY, TOOL_TAVILY_EXTRACT, {"urls": [url]}))
    if fetch_up:
        attempts.append((SERVER_FETCH, TOOL_FETCH, {"url": url}))
    if not attempts:
        return "", "aucun outil de lecture disponible"
    reasons: list[str] = []
    for server, tool, args in attempts:
        ok, text, error = await _try_read(client, server, tool, args)
        if ok and len(text.strip()) > _USEFUL:
            body = text.strip()
            if body.startswith("ERREUR"):
                body = f"Extrait:\n{body}"
            return body, ""
        if error:
            reasons.append(f"{server}.{tool}: {error}")
        elif ok:
            reasons.append(f"{server}.{tool}: contenu insuffisant")
    return "", _one_line("; ".join(reasons)) or "lecture impossible"


def _fit_bodies(pages: list[tuple[str, str]], budget: int) -> dict[str, str]:
    remaining_budget = max(0, budget)
    remaining = len(pages)
    fitted: dict[str, str] = {}
    for url, text in pages:
        allowance = max(_PAGE_MIN, remaining_budget // max(1, remaining))
        body = text.strip()
        if len(body) > allowance:
            body = (
                body[:allowance].rstrip()
                + f"\n…[tronqué à {allowance} caractères]"
            )
        fitted[url] = body
        remaining_budget = max(0, remaining_budget - len(body))
        remaining -= 1
    return fitted


async def read_pages(client: McpClient, urls: list[str]) -> str:
    """Lit jusqu'à 5 URL. Chaque page : Exa, puis Tavily, puis fetch."""
    selected = _select_urls(urls)
    if not selected:
        return "ERREUR: aucune URL http(s) à lire"
    loaded_raw = await asyncio.gather(
        *(_read_one(client, url) for url in selected),
        return_exceptions=True,
    )
    loaded: list[tuple[str, str]] = []
    for item in loaded_raw:
        if isinstance(item, Exception):
            loaded.append(("", f"{type(item).__name__}: {item}"))
        else:
            loaded.append(item)
    rows = list(zip(selected, loaded, strict=True))
    useful = [(url, text) for url, (text, _error) in rows if len(text) > _USEFUL]
    reserve = 200 * len(rows)
    bodies = _fit_bodies(useful, max(_PAGE_MIN, _PAGE_BUDGET - reserve))
    sections: list[str] = []
    for url, (text, error) in rows:
        body = bodies.get(url) if len(text) > _USEFUL else None
        if not body:
            reason = _one_line(error) or "lecture impossible"
            sections.append(f"## {url}\nERREUR: {reason}")
            continue
        sections.append(f"## {url} ({len(body)} caractères)\n{body}")
    rendered = "\n\n".join(sections)
    if len(rendered) > _PAGE_BUDGET:
        return rendered[:_PAGE_BUDGET]
    return rendered


async def research_report(client: McpClient, query: str) -> dict[str, Any]:
    """Recherche approfondie : liens fusionnés, sans synthèse fournisseur."""
    payload = await research_web(client, query)
    engines = [
        str(engine)
        for engine in payload.get("engines") or []
        if str(engine).strip()
    ]
    return {
        "results": list(payload.get("results") or []),
        "engine": "+".join(engines),
        "provider_answer": "",
    }
