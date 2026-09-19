"""Optional tinyfish/Monid link provider for the agentic web search.

Monid exposes a gateway (`api.monid.ai`) whose runs include the tinyfish
web-search/fetch endpoints. It requires an API key (``MONID_API_KEY``);
without one this provider does not exist and the keyless local chain
(DuckDuckGo → specialists → Brave → Tavily) serves every request.

The Monid flow is discover → run: we discover a web-search endpoint and
run it with the query. Any failure returns an empty list so the caller
falls through to the local chain — this provider can never break search.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

DISCOVER_URL = "https://api.monid.ai/v1/discover"
RUN_URL = "https://api.monid.ai/v1/run"
TIMEOUT_S = 30.0


def is_available() -> bool:
    return bool(os.getenv("MONID_API_KEY", "").strip())


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('MONID_API_KEY', '').strip()}",
        "Content-Type": "application/json",
    }


def _discover_endpoint(client: httpx.Client) -> Dict[str, Any] | None:
    response = client.post(
        DISCOVER_URL,
        headers=_auth_headers(),
        json={"query": "web search"},
        timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    endpoints = data.get("endpoints") or data.get("results") or []
    for endpoint in endpoints:
        provider = endpoint.get("provider") or ""
        path = endpoint.get("endpoint") or ""
        if provider and path:
            return {"provider": provider, "endpoint": path}
    return None


def _run_search(
    client: httpx.Client,
    endpoint: Dict[str, Any],
    query: str,
    max_results: int,
) -> List[Dict[str, Any]]:
    response = client.post(
        RUN_URL,
        headers=_auth_headers(),
        json={
            "provider": endpoint["provider"],
            "endpoint": endpoint["endpoint"],
            "input": {"query": query, "maxItems": max_results},
        },
        timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    raw = (
        data.get("results")
        or data.get("data")
        or data.get("output", {}).get("results")
        or []
    )
    links: List[Dict[str, Any]] = []
    for item in raw[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        links.append(
            {
                "title": str(item.get("title") or url)[:200],
                "url": url,
                "snippet": str(item.get("snippet") or item.get("description") or "")[:600],
            }
        )
    return links


def search_links_sync(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search via Monid; returns raw links or raises for the caller to
    fall through to the local chain."""
    if not is_available():
        return []
    with httpx.Client(trust_env=False) as client:
        endpoint = _discover_endpoint(client)
        if endpoint is None:
            return []
        return _run_search(client, endpoint, query, max_results)


async def search_links(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    import asyncio

    return await asyncio.to_thread(search_links_sync, query, max_results)
