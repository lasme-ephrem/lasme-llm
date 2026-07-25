from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.tools.search_ranking import (
    adaptive_select_results,
    score_search_result,
    search_terms,
)
from core.tools.web_search import fetch_url_content, search_web_detailed


SearchFunction = Callable[..., Dict[str, Any]]
FetchFunction = Callable[[str, int], str]


def _relevant_passage(text: str, query: str, max_chars: int = 2_400) -> str:
    """Select compact query-relevant windows from an extracted page."""
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean

    terms = search_terms(query)
    window_size = 900
    stride = 600
    windows: List[tuple[float, int, str]] = []
    for start in range(0, len(clean), stride):
        window = clean[start : start + window_size]
        if not window:
            continue
        window_terms = search_terms(window)
        coverage = len(terms.intersection(window_terms)) / max(1, len(terms))
        early_bonus = max(0.0, 0.08 - (start / max(1, len(clean))) * 0.08)
        windows.append((coverage + early_bonus, start, window))
        if start + window_size >= len(clean):
            break

    chosen = sorted(windows, key=lambda item: item[0], reverse=True)[:3]
    chosen.sort(key=lambda item: item[1])
    passage = " [...] ".join(item[2] for item in chosen)
    return passage[:max_chars].strip()


def _verification_targets(
    results: Iterable[Dict[str, Any]],
    scope: str,
) -> List[Dict[str, Any]]:
    limit = 1 if scope == "direct" else 2 if scope == "standard" else 3
    return list(results)[:limit]


def search_extract_verify(
    query: str,
    max_results: Optional[int] = None,
    deadline_seconds: float = 8.0,
    conversation_messages: Optional[List[Dict[str, str]]] = None,
    *,
    search_fn: SearchFunction = search_web_detailed,
    fetch_fn: FetchFunction = fetch_url_content,
) -> Dict[str, Any]:
    """
    Retrieve candidates, extract the strongest pages, then rerank the evidence.

    The deadline is intentionally bounded: extraction improves grounding, but it
    must never turn a short factual lookup into a minute-long browsing session.
    """
    started = time.monotonic()
    try:
        report = search_fn(
            query,
            max_results,
            conversation_messages=conversation_messages,
        )
    except TypeError as exc:
        # Preserve compatibility with small injected search functions in tests
        # and extensions which still implement the historical two-arg API.
        if "conversation_messages" not in str(exc):
            raise
        report = search_fn(query, max_results)
    results = list(report.get("results", []))
    strategy = dict(report.get("strategy", {}))
    scope = str(strategy.get("scope", "standard"))
    official_domains = list(strategy.get("official_domains", []))
    extracted_count = 0
    extraction_failures: List[str] = []

    # Sonar already performed retrieval and synthesis. Reordering its sources
    # would break the [n] citation mapping, and a second extraction pass would
    # only add latency without improving the provider-grounded response.
    if report.get("answer_mode") == "provider" and report.get("provider_answer"):
        return {
            **report,
            "strategy": {
                **strategy,
                "extracted_count": 0,
                "verified_count": len(results),
                "verification_status": "provider_grounded",
                "elapsed_ms": round((time.monotonic() - started) * 1_000),
                "stop_reason": "provider_answer",
            },
        }

    if not results:
        return {
            **report,
            "strategy": {
                **strategy,
                "extracted_count": 0,
                "verified_count": 0,
                "verification_status": "no_candidates",
                "elapsed_ms": round((time.monotonic() - started) * 1_000),
            },
        }

    enriched: List[Dict[str, Any]] = []
    target_urls = {
        str(item.get("url", ""))
        for item in _verification_targets(results, scope)
    }
    for item in results:
        enriched_item = dict(item)
        enriched_item["search_snippet"] = str(item.get("snippet", ""))
        enriched_item["evidence_kind"] = "search_snippet"
        enriched_item["verified"] = False

        url = str(item.get("url", ""))
        remaining = deadline_seconds - (time.monotonic() - started)
        if url in target_urls and remaining >= 0.75:
            try:
                timeout = max(1, min(4, int(remaining)))
                page_text = fetch_fn(url, timeout)
                passage = _relevant_passage(page_text, query)
                if passage:
                    combined = (
                        f"{enriched_item['search_snippet']} "
                        f"[Contenu extrait de la page] {passage}"
                    ).strip()
                    enriched_item["snippet"] = combined[:4_200]
                    enriched_item["evidence_kind"] = "page_extract"
                    enriched_item["verified"] = True
                    extracted_count += 1
            except Exception as exc:
                extraction_failures.append(f"{url}: {type(exc).__name__}")

        enriched.append(enriched_item)

    # Re-score after extraction. The extracted passage may reveal that a
    # promising search snippet does not actually answer the question.
    rescored = [
        score_search_result(
            item,
            query,
            official_domains=official_domains,
        )
        for item in enriched
    ]
    selected = adaptive_select_results(
        rescored,
        query,
        official_domains=official_domains,
        max_results=max_results,
    )
    final_results = selected.get("results", []) or enriched
    verified_count = sum(bool(item.get("verified")) for item in final_results)
    verification_status = (
        "verified_pages"
        if verified_count
        else "search_snippets_only"
    )

    return {
        **report,
        "status": "ok" if final_results else report.get("status", "unavailable"),
        "results": final_results,
        "errors": [*report.get("errors", []), *extraction_failures],
        "strategy": {
            **strategy,
            **selected.get("strategy", {}),
            "official_domains": official_domains,
            "extracted_count": extracted_count,
            "verified_count": verified_count,
            "verification_status": verification_status,
            "elapsed_ms": round((time.monotonic() - started) * 1_000),
        },
    }

