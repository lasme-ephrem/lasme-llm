"""Optional Monid link provider for the agentic web search.

Monid (``api.monid.ai``) is a gateway over third-party web APIs and exposes
tinyfish web-search endpoints. It requires an API key (``MONID_API_KEY``);
without one this provider does not exist and the keyless local chain
(DuckDuckGo → specialists → Brave → Tavily) serves every request.

Verified live contract:
- ``POST /v1/discover`` ``{"query": "tinyfish"}`` lists candidate endpoints
  with provider, endpoint path, price and quality tags/metrics.
- ``POST /v1/run`` starts a run and answers either synchronously (200 with
  ``status=COMPLETED`` and ``output.results``) or asynchronously (202 with a
  ``runId``) — then poll ``GET /v1/runs/{runId}`` until a terminal status.
- ``resultCount`` in run payloads is unreliable; ``output.results`` is the
  source of truth, sliced client-side to ``max_results`` (tinyfish /search
  has no result-count parameter).

The chosen endpoint is cached on disk for 24 h (``.runtime/monid/``) to skip
a discover per search, and any endpoint whose estimated price exceeds
``MONID_MAX_PRICE_USD`` is refused. Any failure returns an empty list so the
caller falls through to the local chain — this provider can never break
search, and the API key never reaches logs or error messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("Monid")

BASE_URL = "https://api.monid.ai"
DISCOVER_PATH = "/v1/discover"
RUN_PATH = "/v1/run"
RUNS_PATH = "/v1/runs"
DISCOVER_QUERY = "tinyfish"
PREFERRED_PROVIDER = "tinyfish"
PREFERRED_ENDPOINT = "/search"

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_PRICE_USD = 0.01
POLL_INTERVAL_S = 1.0
CACHE_TTL_S = 24 * 3600
CACHE_PATH = (
    Path(__file__).resolve().parents[2] / ".runtime" / "monid" / "endpoint_cache.json"
)
TERMINAL_STATUSES = frozenset(
    {"COMPLETED", "FAILED", "BLOCKED", "STOPPED", "TIMED_OUT"}
)


def is_available() -> bool:
    return bool(os.getenv("MONID_API_KEY", "").strip())


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _redact(text: str) -> str:
    """Strip the API key from any text destined for logs or errors."""
    key = os.getenv("MONID_API_KEY", "").strip()
    return text.replace(key, "***") if key else text


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value >= minimum else default


def _timeout_s() -> float:
    return _env_float("MONID_TIMEOUT_S", DEFAULT_TIMEOUT_S, minimum=0.001)


def _max_price_usd() -> float:
    return _env_float("MONID_MAX_PRICE_USD", DEFAULT_MAX_PRICE_USD, minimum=0.0)


def _unit_price(price: Any) -> float:
    if not isinstance(price, dict):
        return 0.0
    amount = price.get("amount")
    if not isinstance(amount, dict):
        return 0.0
    try:
        return float(amount.get("value") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cost_usd(price: Any, max_results: int) -> float:
    """Estimated run cost: unit price, times results for PER_RESULT billing."""
    if not isinstance(price, dict):
        return 0.0
    value = _unit_price(price)
    if str(price.get("type") or "").strip().upper() == "PER_RESULT":
        return value * max_results
    return value


def _within_budget(price: Any, max_results: int) -> bool:
    cost = _cost_usd(price, max_results)
    cap = _max_price_usd()
    if cost <= cap:
        return True
    logger.warning(
        "[monid] endpoint refused: estimated price %.4f USD exceeds cap %.4f USD",
        cost,
        cap,
    )
    return False


def _cache_load() -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        age = time.time() - float(data.get("cached_at") or 0.0)
    except (TypeError, ValueError):
        return None
    if age > CACHE_TTL_S or not data.get("provider") or not data.get("endpoint"):
        return None
    return data


def _cache_save(provider: str, endpoint: str, price: Any) -> None:
    payload = {
        "provider": provider,
        "endpoint": endpoint,
        "price": price,
        "cached_at": time.time(),
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = CACHE_PATH.with_name(CACHE_PATH.name + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, CACHE_PATH)
    except OSError:
        pass  # the cache is best-effort only


def _rank_candidates(results: List[Any], max_results: int) -> List[Dict[str, Any]]:
    """Order discover results: tinyfish /search first, then verified + stable
    endpoints, then cheapest."""
    candidates: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        endpoint = str(item.get("endpoint") or "").strip()
        if not provider or not endpoint:
            continue
        price = item.get("price")
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        candidates.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "price": price,
                "key": (
                    0
                    if provider == PREFERRED_PROVIDER and endpoint == PREFERRED_ENDPOINT
                    else 1,
                    0 if "verified" in tags else 1,
                    0
                    if str(metrics.get("status") or "").strip().lower() == "stable"
                    else 1,
                    _cost_usd(price, max_results),
                ),
            }
        )
    candidates.sort(key=lambda candidate: candidate["key"])
    return candidates


async def _discover(client: httpx.AsyncClient, api_key: str) -> List[Any]:
    try:
        response = await client.post(
            f"{BASE_URL}{DISCOVER_PATH}",
            headers=_headers(api_key),
            json={"query": DISCOVER_QUERY},
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "[monid] discover failed: %s: %s", type(exc).__name__, _redact(str(exc))
        )
        return []
    if response.status_code >= 400:
        logger.warning("[monid] discover HTTP %s", response.status_code)
        return []
    try:
        data = response.json()
    except ValueError:
        logger.warning("[monid] discover returned invalid JSON")
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


async def _choose_endpoint(
    client: httpx.AsyncClient, api_key: str, max_results: int
) -> Optional[Tuple[str, str]]:
    cached = _cache_load()
    if cached and _within_budget(cached.get("price"), max_results):
        return str(cached["provider"]), str(cached["endpoint"])
    for candidate in _rank_candidates(await _discover(client, api_key), max_results):
        if _within_budget(candidate["price"], max_results):
            _cache_save(candidate["provider"], candidate["endpoint"], candidate["price"])
            return str(candidate["provider"]), str(candidate["endpoint"])
    logger.warning("[monid] no endpoint within price cap")
    return None


async def _poll_run(
    client: httpx.AsyncClient, api_key: str, run_id: str, deadline: float
) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}{RUNS_PATH}/{run_id}"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("[monid] polling timed out")
            return None
        try:
            response = await client.get(url, headers=_headers(api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "[monid] poll failed: %s: %s", type(exc).__name__, _redact(str(exc))
            )
            return None
        if response.status_code >= 400:
            logger.warning("[monid] poll HTTP %s", response.status_code)
            return None
        try:
            data = response.json()
        except ValueError:
            logger.warning("[monid] poll returned invalid JSON")
            return None
        status = str(data.get("status") or "").strip().upper() if isinstance(data, dict) else ""
        if status in TERMINAL_STATUSES:
            return data
        await asyncio.sleep(min(POLL_INTERVAL_S, remaining))


def _map_results(raw: List[Any], max_results: int) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []
    for item in raw:
        if len(links) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        links.append(
            {
                "title": str(item.get("title") or url).strip()[:200],
                "url": url,
                "snippet": str(
                    item.get("snippet") or item.get("description") or ""
                ).strip()[:600],
            }
        )
    return links


async def _run_search(
    client: httpx.AsyncClient,
    api_key: str,
    provider: str,
    endpoint: str,
    query: str,
    max_results: int,
    deadline: float,
) -> List[Dict[str, Any]]:
    purpose = f"web search for: {query}"[:200]
    try:
        response = await client.post(
            f"{BASE_URL}{RUN_PATH}",
            headers=_headers(api_key),
            json={
                "provider": provider,
                "endpoint": endpoint,
                "input": {"queryParams": {"query": query, "purpose": purpose}},
            },
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "[monid] run failed: %s: %s", type(exc).__name__, _redact(str(exc))
        )
        return []
    if response.status_code >= 400:
        logger.warning("[monid] run HTTP %s", response.status_code)
        return []
    try:
        data = response.json()
    except ValueError:
        logger.warning("[monid] run returned invalid JSON")
        return []
    if not isinstance(data, dict):
        return []
    status = str(data.get("status") or "").strip().upper()
    if status not in TERMINAL_STATUSES:
        run_id = str(data.get("runId") or "").strip()
        if not run_id:
            logger.warning("[monid] run response has neither terminal status nor runId")
            return []
        polled = await _poll_run(client, api_key, run_id, deadline)
        if polled is None:
            return []
        data = polled
        status = str(data.get("status") or "").strip().upper()
    if status != "COMPLETED":
        logger.warning("[monid] run ended with status %s", status or "UNKNOWN")
        return []
    # resultCount is unreliable (observed 0 with 9 actual results):
    # output.results is the source of truth.
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    raw = output.get("results") if isinstance(output.get("results"), list) else []
    links = _map_results(raw, max_results)
    price = data.get("price") if isinstance(data.get("price"), dict) else {}
    amount = price.get("amount") if isinstance(price.get("amount"), dict) else {}
    logger.info(
        "[monid] run ok provider=%s endpoint=%s price=%.4f %s billed_units=%s results=%d",
        provider,
        endpoint,
        _unit_price(price),
        str(amount.get("currency") or "USD"),
        data.get("billedUnits"),
        len(links),
    )
    return links


async def search_links(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search via Monid/tinyfish. Always returns a list — never raises — so
    the caller can fall through to the keyless local chain."""
    query = str(query or "").strip()
    if not query or not is_available():
        return []
    try:
        max_results = max(1, int(max_results))
    except (TypeError, ValueError):
        max_results = 5
    api_key = os.getenv("MONID_API_KEY", "").strip()
    timeout_s = _timeout_s()
    deadline = time.monotonic() + timeout_s  # covers run + polling
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout_s) as client:
            chosen = await _choose_endpoint(client, api_key, max_results)
            if chosen is None:
                return []
            provider, endpoint = chosen
            return await _run_search(
                client, api_key, provider, endpoint, query, max_results, deadline
            )
    except Exception as exc:  # never propagate, and never leak the key
        logger.warning(
            "[monid] search failed: %s: %s", type(exc).__name__, _redact(str(exc))
        )
        return []


def search_links_sync(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Blocking wrapper around :func:`search_links` (same silent-failure
    contract); safe to call with or without a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(search_links(query, max_results))
    # Already inside a running loop: drive the coroutine on a private loop in
    # a worker thread so the caller's loop is never blocked.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, search_links(query, max_results)).result()
