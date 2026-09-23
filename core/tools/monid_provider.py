"""Optional Monid link provider for the agentic web search.

Monid (``api.monid.ai``) is a gateway over third-party web APIs and exposes
tinyfish web-search endpoints. It requires an API key (``MONID_API_KEY``);
without one this provider does not exist and the keyless local chain
(DuckDuckGo → specialists → Brave → Tavily) serves every request.

Verified live contract:
- ``POST /v1/discover`` ``{"query": "web search"}`` lists candidate endpoints
  with provider, endpoint path, price and quality tags/metrics.
- ``POST /v1/run`` starts a run and answers either synchronously (200 with
  ``status=COMPLETED`` and ``output.results``) or asynchronously (202 with a
  ``runId``) — then poll ``GET /v1/runs/{runId}`` until a terminal status.
- ``resultCount`` in run payloads is unreliable; ``output.results`` is the
  source of truth, sliced client-side (tinyfish /search has no result-count
  parameter). Octen nests its list under ``output.data.results``.
- tinyfish /search (GET-style ``queryParams``, free) accepts rich ranking
  params: ``purpose``, ``domain_type`` (web|news|research_paper),
  ``language``, ``location``, ``include_domains``/``exclude_domains``,
  ``recency_minutes``, ``after_date``/``before_date``, ``page``.
- Cross-checked secondaries (POST-style ``body`` inputs):
  context.dev /web/search (PER_RESULT, ~$0.00009/result, billed per page of
  10), octen /search ($0.001 per call, ``time_range`` ∈ day|week|month|year),
  exa /search ($0.01 per call, ISO ``startPublishedDate``).

The chosen endpoints are cached on disk for 24 h (``.runtime/monid/``) to
skip a discover per search, and any endpoint whose estimated price exceeds
``MONID_MAX_PRICE_USD`` is refused. :func:`search_links_cross` fans out over
tinyfish plus the best affordable secondary in parallel and merges the
results (dedup by normalized URL, per-engine tracing). Any failure returns
an empty list so the caller falls through to the local chain — this provider
can never break search, and the API key never reaches logs or errors.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx

logger = logging.getLogger("Monid")

BASE_URL = "https://api.monid.ai"
DISCOVER_PATH = "/v1/discover"
RUN_PATH = "/v1/run"
RUNS_PATH = "/v1/runs"
DISCOVER_QUERY = "web search"
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

# Cross-search ("armée croisée"): the primary tinyfish leg always runs
# (free, browser-rendered); one secondary engine is launched in parallel
# for corroboration. Candidates below are the verified web-search-capable
# POST-body endpoints of the gateway; the best affordable one is picked at
# run time from the live discover data.
CROSS_SECONDARY_SPECS = frozenset(
    {
        ("exa", "/search"),
        ("context.dev", "/web/search"),
        ("octen", "/search"),
    }
)
VALID_DOMAIN_TYPES = frozenset({"web", "news", "research_paper"})
MAX_PAGE = 10  # tinyfish /search page range is 0..10
# context.dev bills PER_RESULT with a hard floor of 10 results per call
# (numResults minimum), so its real cost must be sized on max(n, 10).
PER_RESULT_FLOOR_RESULTS = 10
# Maximum links returned by search_links_cross: the caller's chain applies
# its own relevance ranking, so a small overlap buffer survives dedup.
CROSS_RESULT_BUFFER = 4


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
    if str(price.get("type") or "").strip().upper() in {"PER_RESULT", "PER_UNIT"}:
        return value * max(1, max_results)
    return value


def _cost_ok(price: Any, max_results: int) -> bool:
    """Silent budget check (used when ranking candidates)."""
    return _cost_usd(price, max_results) <= _max_price_usd()


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


def _cache_save(
    provider: str,
    endpoint: str,
    price: Any,
    secondary: Optional[Dict[str, Any]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "provider": provider,
        "endpoint": endpoint,
        "price": price,
        "cached_at": time.time(),
    }
    # Only a cross-search writes the secondary slot; a legacy cache without
    # the key tells search_links_cross to discover once and fill it.
    if secondary is not None:
        payload["secondary"] = secondary
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


def _secondary_sizing(provider: str, max_results: int) -> int:
    """Result count used to size a secondary's real cost for this request."""
    if provider == "context.dev":
        return max(max_results, PER_RESULT_FLOOR_RESULTS)
    return max_results


def _pick_secondary(
    candidates: List[Dict[str, Any]], max_results: int
) -> Optional[Dict[str, Any]]:
    """Best affordable cross-check endpoint: verified + stable first, then
    the cheapest for the actual request size. tinyfish itself is never the
    secondary (it is the primary leg)."""
    pool = [
        candidate
        for candidate in candidates
        if (candidate["provider"], candidate["endpoint"]) in CROSS_SECONDARY_SPECS
        and not (
            candidate["provider"] == PREFERRED_PROVIDER
            and candidate["endpoint"] == PREFERRED_ENDPOINT
        )
    ]
    affordable = [
        candidate
        for candidate in pool
        if _cost_ok(
            candidate["price"],
            _secondary_sizing(str(candidate["provider"]), max_results),
        )
    ]
    if not affordable:
        return None
    affordable.sort(
        key=lambda candidate: (
            _cost_usd(
                candidate["price"],
                _secondary_sizing(str(candidate["provider"]), max_results),
            ),
        )
    )
    return affordable[0]


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


async def _resolve_targets(
    client: httpx.AsyncClient, api_key: str, max_results: int, *, want_secondary: bool
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Primary (tinyfish-preferred) and optional cross-search secondary.

    Disk cache first; a cache entry without the ``secondary`` slot (single
    search or legacy write) triggers one discover so the cross-search can
    fill it, then re-saves the pair.
    """
    cached = _cache_load()
    primary: Optional[Dict[str, Any]] = None
    if cached and _cost_ok(cached.get("price"), max_results):
        primary = {
            "provider": str(cached["provider"]),
            "endpoint": str(cached["endpoint"]),
            "price": cached.get("price"),
        }
    secondary: Optional[Dict[str, Any]] = None
    has_secondary_slot = isinstance(cached, dict) and "secondary" in cached
    if has_secondary_slot:
        raw = cached.get("secondary")
        if (
            isinstance(raw, dict)
            and raw.get("provider")
            and raw.get("endpoint")
            and _cost_ok(raw.get("price"), _secondary_sizing(str(raw["provider"]), max_results))
        ):
            secondary = {
                "provider": str(raw["provider"]),
                "endpoint": str(raw["endpoint"]),
                "price": raw.get("price"),
            }
    if primary is not None and (not want_secondary or has_secondary_slot):
        return primary, secondary

    candidates = _rank_candidates(await _discover(client, api_key), max_results)
    if primary is None:
        for candidate in candidates:
            if _within_budget(candidate["price"], max_results):
                primary = candidate
                break
        if primary is None:
            logger.warning("[monid] no endpoint within price cap")
            return None, None
    if want_secondary:
        secondary = _pick_secondary(candidates, max_results)
        if secondary is None:
            logger.info("[monid] no affordable secondary endpoint for cross-search")
    if not has_secondary_slot or primary["provider"] != str(cached.get("provider")):
        _cache_save(
            str(primary["provider"]),
            str(primary["endpoint"]),
            primary["price"],
            secondary=(
                {
                    "provider": secondary["provider"],
                    "endpoint": secondary["endpoint"],
                    "price": secondary["price"],
                }
                if secondary
                else None
            ),
        )
    return primary, secondary


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
        url = str(item.get("url") or item.get("link") or item.get("id") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        links.append(
            {
                "title": str(item.get("title") or url).strip()[:200],
                "url": url,
                "snippet": str(
                    item.get("snippet")
                    or item.get("description")
                    or item.get("highlight")
                    or ""
                ).strip()[:600],
            }
        )
    return links


def _extract_results(data: Dict[str, Any]) -> List[Any]:
    """``output.results`` is the source of truth; octen nests it one level
    deeper under ``output.data.results``. resultCount stays ignored (unreliable)."""
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    raw = output.get("results")
    if not isinstance(raw, list):
        nested = output.get("data")
        raw = nested.get("results") if isinstance(nested, dict) else None
    return raw if isinstance(raw, list) else []


async def _run_search(
    client: httpx.AsyncClient,
    api_key: str,
    provider: str,
    endpoint: str,
    run_input: Dict[str, Any],
    max_results: int,
    deadline: float,
) -> List[Dict[str, Any]]:
    try:
        response = await client.post(
            f"{BASE_URL}{RUN_PATH}",
            headers=_headers(api_key),
            json={
                "provider": provider,
                "endpoint": endpoint,
                "input": run_input,
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
    links = _map_results(_extract_results(data), max_results)
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


# --- Rich parameter plumbing -------------------------------------------------


def _default_purpose(query: str) -> str:
    return f"web search for: {query}"[:200]


def _clean_domain_list(domains: Any) -> Optional[List[str]]:
    """Normalize an include/exclude list: non-empty strings only."""
    if not domains:
        return None
    if isinstance(domains, str):
        domains = [domains]
    if not isinstance(domains, (list, tuple, set)):
        return None
    cleaned = [str(domain).strip() for domain in domains if str(domain).strip()]
    return cleaned or None


def _tinyfish_query_params(
    query: str,
    purpose: str,
    *,
    domain_type: Optional[str],
    include_domains: Optional[List[str]],
    exclude_domains: Optional[List[str]],
    recency_minutes: Optional[int],
    language: Optional[str],
    page: int,
) -> Dict[str, Any]:
    """tinyfish /search GET-style queryParams; only non-empty params travel."""
    params: Dict[str, Any] = {"query": query, "purpose": purpose}
    if domain_type in VALID_DOMAIN_TYPES:
        params["domain_type"] = domain_type
    if include_domains:
        params["include_domains"] = list(include_domains)
    if exclude_domains:
        params["exclude_domains"] = list(exclude_domains)
    if recency_minutes and recency_minutes > 0:
        params["recency_minutes"] = int(recency_minutes)
    if language and str(language).strip():
        params["language"] = str(language).strip()
    if page and page > 0:
        params["page"] = max(0, min(int(page), MAX_PAGE))
    return params


def _recency_bucket(recency_minutes: int) -> str:
    """Coarse day/week/month/year bucket from a minute-based window."""
    if recency_minutes <= 1440:
        return "day"
    if recency_minutes <= 10080:
        return "week"
    if recency_minutes <= 43200:
        return "month"
    return "year"


def _secondary_body(
    provider: str,
    endpoint: str,
    query: str,
    max_results: int,
    *,
    domain_type: Optional[str],
    include_domains: Optional[List[str]],
    exclude_domains: Optional[List[str]],
    recency_minutes: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Best-effort POST body for a cross-search secondary: the generic intent
    (query + domain filters + freshness + news orientation) is translated per
    provider; unsupported params are simply dropped, never guessed."""
    count = max(1, min(int(max_results), 100))
    if provider == "context.dev" and endpoint == "/web/search":
        body: Dict[str, Any] = {
            "query": query[:500],
            "numResults": max(count, PER_RESULT_FLOOR_RESULTS),
        }
        if include_domains:
            body["includeDomains"] = list(include_domains)
        if exclude_domains:
            body["excludeDomains"] = list(exclude_domains)
        if recency_minutes and recency_minutes > 0:
            body["freshness"] = {
                "day": "last_24_hours",
                "week": "last_week",
                "month": "last_month",
                "year": "last_year",
            }[_recency_bucket(recency_minutes)]
        return {"body": body}
    if provider == "octen" and endpoint == "/search":
        body = {"query": query, "count": count}
        if include_domains:
            body["include_domains"] = list(include_domains)
        if exclude_domains:
            body["exclude_domains"] = list(exclude_domains)
        if domain_type == "news":
            body["topic"] = "news"
        if recency_minutes and recency_minutes > 0:
            body["time_range"] = _recency_bucket(recency_minutes)
        return {"body": body}
    if provider == "exa" and endpoint == "/search":
        body = {"query": query, "numResults": count}
        if include_domains:
            body["includeDomains"] = list(include_domains)
        if exclude_domains:
            body["excludeDomains"] = list(exclude_domains)
        if domain_type == "news":
            body["category"] = "news"
        if recency_minutes and recency_minutes > 0:
            started = datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(minutes=int(recency_minutes))
            body["startPublishedDate"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"body": body}
    return None


# Tracking params stripped when building a cross-engine dedup key (mirrors
# the chain-level canonicalization in search_ranking).
TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_")


def _normalize_url(url: str) -> str:
    """Cross-engine dedup key: same resource regardless of scheme spelling,
    www prefix, fragment, trailing slash or tracking query params."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip().casefold()
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.rstrip("/")
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith(TRACKING_QUERY_PREFIXES)
    ]
    query = f"?{urlencode(kept)}" if kept else ""
    return f"{host}{path}{query}"


# --- Public API ---------------------------------------------------------------


async def search_links(
    query: str,
    max_results: int = 5,
    *,
    purpose: Optional[str] = None,
    domain_type: Optional[str] = None,
    include_domains: Any = None,
    exclude_domains: Any = None,
    recency_minutes: Optional[int] = None,
    language: Optional[str] = None,
    page: int = 0,
) -> List[Dict[str, Any]]:
    """Search via Monid (tinyfish-preferred endpoint). Always returns a list
    — never raises — so the caller can fall through to the local chain.

    Rich ranking params (verified tinyfish /search contract) are forwarded
    when set; invalid values are ignored rather than rejected so a bad caller
    hint can never break the search.
    """
    query = str(query or "").strip()
    if not query or not is_available():
        return []
    try:
        max_results = max(1, int(max_results))
    except (TypeError, ValueError):
        max_results = 5
    if domain_type is not None and domain_type not in VALID_DOMAIN_TYPES:
        logger.info("[monid] ignoring invalid domain_type %r", domain_type)
        domain_type = None
    try:
        recency_minutes = (
            int(recency_minutes) if recency_minutes and int(recency_minutes) > 0 else None
        )
    except (TypeError, ValueError):
        recency_minutes = None
    try:
        page = max(0, min(int(page), MAX_PAGE))
    except (TypeError, ValueError):
        page = 0
    include_list = _clean_domain_list(include_domains)
    exclude_list = _clean_domain_list(exclude_domains)
    purpose = str(purpose).strip()[:200] if purpose and str(purpose).strip() else (
        _default_purpose(query)
    )

    run_input = {
        "queryParams": _tinyfish_query_params(
            query,
            purpose,
            domain_type=domain_type,
            include_domains=include_list,
            exclude_domains=exclude_list,
            recency_minutes=recency_minutes,
            language=language,
            page=page,
        )
    }
    api_key = os.getenv("MONID_API_KEY", "").strip()
    timeout_s = _timeout_s()
    deadline = time.monotonic() + timeout_s  # covers run + polling
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout_s) as client:
            primary, _ = await _resolve_targets(
                client, api_key, max_results, want_secondary=False
            )
            if primary is None:
                return []
            return await _run_search(
                client,
                api_key,
                str(primary["provider"]),
                str(primary["endpoint"]),
                run_input,
                max_results,
                deadline,
            )
    except Exception as exc:  # never propagate, and never leak the key
        logger.warning(
            "[monid] search failed: %s: %s", type(exc).__name__, _redact(str(exc))
        )
        return []


async def search_links_cross(
    query: str,
    max_results: int = 5,
    **params: Any,
) -> List[Dict[str, Any]]:
    """Cross-checked search: tinyfish /search (free, always) plus the best
    affordable secondary engine (context.dev / octen / exa), run in
    parallel, merged with normalized-URL dedup.

    Each link carries an ``engine`` field — ``"monid"`` for tinyfish,
    ``"monid:<provider>"`` for the secondary — so callers can trace which
    engine surfaced it. Up to ``max_results + CROSS_RESULT_BUFFER`` links are
    returned: the caller's ranking chain performs the final triage. If the
    secondary is unavailable or over budget the tinyfish-only result is
    returned without any error.
    """
    query = str(query or "").strip()
    if not query or not is_available():
        return []
    try:
        max_results = max(1, int(max_results))
    except (TypeError, ValueError):
        max_results = 5
    budget = max_results + CROSS_RESULT_BUFFER

    if domain_type := params.get("domain_type"):
        if domain_type not in VALID_DOMAIN_TYPES:
            logger.info("[monid] ignoring invalid domain_type %r", domain_type)
            params["domain_type"] = None
    try:
        recency = params.get("recency_minutes")
        params["recency_minutes"] = (
            int(recency) if recency and int(recency) > 0 else None
        )
    except (TypeError, ValueError):
        params["recency_minutes"] = None

    purpose = str(params.get("purpose") or "").strip()[:200] or _default_purpose(query)
    include_list = _clean_domain_list(params.get("include_domains"))
    exclude_list = _clean_domain_list(params.get("exclude_domains"))
    domain_type = params.get("domain_type") or None
    recency_minutes = params.get("recency_minutes")
    language = params.get("language")
    try:
        page = max(0, min(int(params.get("page") or 0), MAX_PAGE))
    except (TypeError, ValueError):
        page = 0

    tinyfish_input = {
        "queryParams": _tinyfish_query_params(
            query,
            purpose,
            domain_type=domain_type,
            include_domains=include_list,
            exclude_domains=exclude_list,
            recency_minutes=recency_minutes,
            language=language,
            page=page,
        )
    }

    api_key = os.getenv("MONID_API_KEY", "").strip()
    timeout_s = _timeout_s()
    deadline = time.monotonic() + timeout_s

    async def _tinyfish_leg(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        return await _run_search(
            client,
            api_key,
            PREFERRED_PROVIDER,
            PREFERRED_ENDPOINT,
            tinyfish_input,
            budget,
            deadline,
        )

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout_s) as client:
            tinyfish_task = asyncio.create_task(_tinyfish_leg(client))
            secondary: Optional[Dict[str, Any]] = None
            try:
                primary, secondary = await _resolve_targets(
                    client, api_key, max_results, want_secondary=True
                )
            except Exception as exc:
                logger.warning(
                    "[monid] secondary selection failed: %s: %s",
                    type(exc).__name__,
                    _redact(str(exc)),
                )
            secondary_body = None
            if secondary is not None:
                secondary_body = _secondary_body(
                    str(secondary["provider"]),
                    str(secondary["endpoint"]),
                    query,
                    _secondary_sizing(str(secondary["provider"]), max_results),
                    domain_type=domain_type,
                    include_domains=include_list,
                    exclude_domains=exclude_list,
                    recency_minutes=recency_minutes,
                )
            if secondary is None or secondary_body is None:
                # No usable secondary: tinyfish alone, no error.
                return [
                    {**link, "engine": "monid"} for link in await tinyfish_task
                ]

            async def _secondary_leg(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
                return await _run_search(
                    client,
                    api_key,
                    str(secondary["provider"]),
                    str(secondary["endpoint"]),
                    secondary_body,
                    budget,
                    deadline,
                )

            tasks = [tinyfish_task, asyncio.create_task(_secondary_leg(client))]
            # Global budget: the timeout already consumed by discovery is
            # deducted so discovery + both runs fit in MONID_TIMEOUT_S.
            remaining = deadline - time.monotonic()
            done, pending = await asyncio.wait(
                set(tasks), timeout=max(0.001, remaining)
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            def _task_result(task: asyncio.Task) -> List[Dict[str, Any]]:
                if task not in done or task.cancelled():
                    return []
                exc = task.exception()
                if exc is not None:
                    logger.warning(
                        "[monid] cross leg failed: %s: %s",
                        type(exc).__name__,
                        _redact(str(exc)),
                    )
                    return []
                return task.result() or []

            tinyfish_links = _task_result(tasks[0])
            secondary_links = _task_result(tasks[1])
            if pending:
                logger.info(
                    "[monid] cross leg cancelled at timeout: %d leg(s)",
                    len(pending),
                )

            merged: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for engine, links in (
                ("monid", tinyfish_links),
                (f"monid:{secondary['provider']}", secondary_links),
            ):
                for link in links or []:
                    key = _normalize_url(str(link.get("url") or ""))
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append({**link, "engine": engine})
            return merged[:budget]
    except Exception as exc:  # never propagate, and never leak the key
        logger.warning(
            "[monid] cross search failed: %s: %s", type(exc).__name__, _redact(str(exc))
        )
        return []


def search_links_sync(
    query: str, max_results: int = 5, **params: Any
) -> List[Dict[str, Any]]:
    """Blocking wrapper around :func:`search_links` (same silent-failure
    contract); safe to call with or without a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(search_links(query, max_results, **params))
    # Already inside a running loop: drive the coroutine on a private loop in
    # a worker thread so the caller's loop is never blocked.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, search_links(query, max_results, **params)
        ).result()
