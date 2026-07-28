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

    def invoke_search(*, full_chain: bool = False) -> Optional[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {
            "conversation_messages": conversation_messages,
        }
        if full_chain:
            kwargs.update(
                {
                    "force_full_chain": True,
                    "skip_primary_provider": True,
                }
            )
        try:
            return search_fn(query, max_results, **kwargs)
        except TypeError as exc:
            # Preserve compatibility with injected historical two-argument
            # search functions. They cannot perform a post-verification retry.
            if full_chain:
                return None
            if "conversation_messages" not in str(exc):
                raise
            return search_fn(query, max_results)

    report = invoke_search() or {}
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

    def enrich_results(
        candidates: List[Dict[str, Any]],
        current_scope: str,
        previous: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        nonlocal extracted_count
        previous = previous or {}
        target_urls = {
            str(item.get("url", ""))
            for item in _verification_targets(candidates, current_scope)
        }
        enriched_items: List[Dict[str, Any]] = []
        for item in candidates:
            url = str(item.get("url", ""))
            existing = previous.get(url)
            if existing and existing.get("verified"):
                enriched_items.append(existing)
                continue
            enriched_item = dict(item)
            enriched_item["search_snippet"] = str(item.get("snippet", ""))
            structured = (
                item.get("evidence_kind") == "structured_api"
                or str(item.get("engine", "")) in {
                    "OpenAlex",
                    "GDELT",
                    "Wikimedia",
                    "Wikipedia",
                }
            )
            enriched_item["evidence_kind"] = (
                "structured_api" if structured else "search_snippet"
            )
            enriched_item["verified"] = bool(structured)

            remaining = deadline_seconds - (time.monotonic() - started)
            if url in target_urls and remaining >= 0.75 and not structured:
                try:
                    timeout = max(1, min(4, int(remaining)))
                    page_text = fetch_fn(url, timeout)
                    passage = _relevant_passage(page_text, query)
                    if passage:
                        # Rank the source on what the page actually contains,
                        # not on a potentially misleading search snippet.
                        enriched_item["snippet"] = passage[:4_200]
                        enriched_item["evidence_kind"] = "page_extract"
                        query_terms = search_terms(query)
                        passage_coverage = (
                            len(query_terms.intersection(search_terms(passage)))
                            / max(1, len(query_terms))
                        )
                        enriched_item["verification_coverage"] = round(
                            passage_coverage,
                            4,
                        )
                        enriched_item["verified"] = passage_coverage >= 0.12
                        enriched_item["verification_rejected"] = (
                            passage_coverage < 0.12
                        )
                        if enriched_item["verified"]:
                            extracted_count += 1
                except Exception as exc:
                    extraction_failures.append(
                        f"{url}: {type(exc).__name__}"
                    )
            enriched_items.append(enriched_item)
        return enriched_items

    def select_evidence(
        enriched_items: List[Dict[str, Any]],
        current_official_domains: List[str],
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], int]:
        rescored = [
            score_search_result(
                item,
                query,
                official_domains=current_official_domains,
            )
            for item in enriched_items
            if not item.get("verification_rejected")
        ]
        selection = adaptive_select_results(
            rescored,
            query,
            official_domains=current_official_domains,
            max_results=max_results,
        )
        final = list(selection.get("results", []))
        verified = sum(bool(item.get("verified")) for item in final)
        selection_strategy = dict(selection.get("strategy", {}))
        if selection_strategy.get("sufficient") and final and not verified:
            selection_strategy["sufficient"] = False
            selection_strategy["stop_reason"] = "page_verification_required"
        selection["strategy"] = selection_strategy
        return selection, final, verified

    enriched = enrich_results(results, scope)
    selected, final_results, verified_count = select_evidence(
        enriched,
        official_domains,
    )

    # A snippet can look perfect while the underlying page says something
    # else. When verification invalidates the first batch, continue once
    # through the remaining configured providers (without billing Sonar twice).
    expanded_after_verification = False
    remaining = deadline_seconds - (time.monotonic() - started)
    if (
        not selected.get("strategy", {}).get("sufficient")
        and remaining >= 1.5
    ):
        expanded_report = invoke_search(full_chain=True)
        if expanded_report:
            expanded_after_verification = True
            expanded_results = list(expanded_report.get("results", []))
            merged_by_url = {
                str(item.get("url", "")): item
                for item in [*expanded_results, *results]
                if item.get("url")
            }
            previous = {
                str(item.get("url", "")): item
                for item in enriched
                if item.get("url")
            }
            strategy = {
                **strategy,
                **dict(expanded_report.get("strategy", {})),
            }
            official_domains = list(
                strategy.get("official_domains", official_domains)
            )
            scope = str(strategy.get("scope", scope))
            enriched = enrich_results(
                list(merged_by_url.values()),
                scope,
                previous,
            )
            selected, final_results, verified_count = select_evidence(
                enriched,
                official_domains,
            )
            report = {
                **report,
                "engine": expanded_report.get("engine") or report.get("engine"),
                "errors": [
                    *report.get("errors", []),
                    *expanded_report.get("errors", []),
                ],
            }

    verification_status = (
        "verified_pages"
        if verified_count
        else (
            "unverified_snippets"
            if final_results
            else "no_verified_evidence"
        )
    )

    return {
        **report,
        "status": "ok" if final_results else "unavailable",
        "results": final_results,
        "errors": [*report.get("errors", []), *extraction_failures],
        "strategy": {
            **strategy,
            **selected.get("strategy", {}),
            "official_domains": official_domains,
            "extracted_count": extracted_count,
            "verified_count": verified_count,
            "verification_status": verification_status,
            "expanded_after_verification": expanded_after_verification,
            "elapsed_ms": round((time.monotonic() - started) * 1_000),
        },
    }

