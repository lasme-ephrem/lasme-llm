from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, List, Optional

import httpx

from core.security import validate_public_http_url


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
WIKIPEDIA_API_URL = "https://fr.wikipedia.org/w/api.php"

ACADEMIC_MARKERS = {
    "article scientifique",
    "articles scientifiques",
    "academique",
    "arxiv",
    "doi",
    "etude",
    "etudes",
    "meta analyse",
    "papier scientifique",
    "publication scientifique",
    "publications scientifiques",
    "recherche scientifique",
    "revue scientifique",
}
NEWS_MARKERS = {
    "actualite",
    "actualites",
    "dans la presse",
    "derniere nouvelle",
    "dernieres nouvelles",
    "journalistes",
    "medias",
    "news",
}
KNOWLEDGE_MARKERS = {
    "auteur de",
    "capitale de",
    "createur de",
    "date de naissance",
    "fondateur de",
    "histoire de",
    "invente par",
    "lieu de naissance",
    "population de",
    "qu est ce que",
    "qui est",
}


class SearchProviderError(RuntimeError):
    """Provider failure whose message never contains credentials or bodies."""

    def __init__(
        self,
        provider: str,
        reason: str,
        status_code: int | None = None,
    ):
        self.provider = provider
        self.reason = reason
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"{provider}: {reason}{suffix}")


def provider_error_reason(status_code: int) -> str:
    if status_code in {402, 429}:
        return "quota_or_rate_limit"
    if status_code in {401, 403}:
        return "authentication_failed"
    if status_code >= 500:
        return "provider_unavailable"
    return "request_rejected"


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def detect_search_vertical(query: str) -> Optional[str]:
    """Return a specialist only for explicit, high-confidence intents."""
    normalized = _normalized(query)
    if any(marker in normalized for marker in ACADEMIC_MARKERS):
        return "academic"
    if any(marker in normalized for marker in NEWS_MARKERS):
        return "news"
    if any(marker in normalized for marker in KNOWLEDGE_MARKERS):
        return "knowledge"
    return None


def _raise_for_provider(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    raise SearchProviderError(
        provider,
        provider_error_reason(response.status_code),
        response.status_code,
    )


def search_brave(
    query: str,
    api_key: str,
    candidate_limit: int,
    *,
    timeout: float = 7.0,
) -> Dict[str, Any]:
    """Search Brave's independent Web index and return normalized candidates."""
    if not api_key:
        return {"results": [], "quota": {}}

    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(3.0, timeout)),
            follow_redirects=False,
            trust_env=False,
        ) as http:
            response = http.get(
                BRAVE_SEARCH_URL,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                params={
                    "q": query,
                    "count": max(1, min(candidate_limit, 20)),
                    "country": "fr",
                    "search_lang": "fr",
                    "spellcheck": "1",
                    "extra_snippets": "true",
                },
            )
    except httpx.TimeoutException as exc:
        raise SearchProviderError("Brave Search", "timeout") from exc
    except httpx.HTTPError as exc:
        raise SearchProviderError("Brave Search", "network_error") from exc

    _raise_for_provider(response, "Brave Search")
    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError(
            "Brave Search",
            "invalid_json_response",
        ) from exc

    results: List[Dict[str, Any]] = []
    raw_results = ((data.get("web") or {}).get("results") or [])
    for index, item in enumerate(raw_results[:candidate_limit]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippets = [
            str(item.get("description") or "").strip(),
            *[
                str(value).strip()
                for value in (item.get("extra_snippets") or [])
                if str(value).strip()
            ],
        ]
        snippet = " ".join(dict.fromkeys(value for value in snippets if value))
        if not title or not url or not snippet:
            continue
        try:
            safe_url = validate_public_http_url(url)
        except ValueError:
            continue
        results.append(
            {
                "title": title,
                "snippet": snippet[:3_600],
                "url": safe_url,
                "engine": "Brave Search",
                "engine_score": max(0.48, 0.92 - index * 0.035),
            }
        )

    quota = {
        "limit": response.headers.get("X-RateLimit-Limit"),
        "remaining": response.headers.get("X-RateLimit-Remaining"),
        "reset": response.headers.get("X-RateLimit-Reset"),
    }
    return {
        "results": results,
        "quota": {key: value for key, value in quota.items() if value is not None},
    }


def search_gdelt(
    query: str,
    candidate_limit: int,
    *,
    timeout: float = 6.0,
) -> List[Dict[str, Any]]:
    """Retrieve recent news candidates from the free GDELT DOC API."""
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(3.0, timeout)),
            follow_redirects=False,
            trust_env=False,
        ) as http:
            response = http.get(
                GDELT_DOC_URL,
                params={
                    "query": query,
                    "mode": "artlist",
                    "maxrecords": max(1, min(candidate_limit, 50)),
                    "format": "json",
                    "sort": "datedesc",
                    "timespan": "3months",
                },
            )
    except httpx.TimeoutException as exc:
        raise SearchProviderError("GDELT", "timeout") from exc
    except httpx.HTTPError as exc:
        raise SearchProviderError("GDELT", "network_error") from exc

    _raise_for_provider(response, "GDELT")
    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError("GDELT", "invalid_json_response") from exc

    results: List[Dict[str, Any]] = []
    for index, item in enumerate((data.get("articles") or [])[:candidate_limit]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        try:
            safe_url = validate_public_http_url(url)
        except ValueError:
            continue
        domain = str(item.get("domain") or "").strip()
        seen_date = str(item.get("seendate") or "").strip()
        source_country = str(item.get("sourcecountry") or "").strip()
        snippet = (
            f"Article d'actualité intitulé « {title} ». "
            f"Source : {domain or 'média Web'}."
        )
        if seen_date:
            snippet += f" Référencé par GDELT le {seen_date}."
        if source_country:
            snippet += f" Pays de la source : {source_country}."
        results.append(
            {
                "title": title,
                "snippet": snippet,
                "url": safe_url,
                "engine": "GDELT",
                "engine_score": max(0.42, 0.82 - index * 0.035),
            }
        )
    return results

def _openalex_abstract(inverted_index: Any, max_chars: int = 1_800) -> str:
    if not isinstance(inverted_index, dict):
        return ""
    positioned: List[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned.append((position, str(word)))
    return " ".join(word for _, word in sorted(positioned))[:max_chars]


def search_openalex(
    query: str,
    api_key: str,
    candidate_limit: int,
    *,
    timeout: float = 6.0,
) -> List[Dict[str, Any]]:
    """Search scholarly works through OpenAlex's structured API."""
    if not api_key:
        return []
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(3.0, timeout)),
            follow_redirects=False,
            trust_env=False,
        ) as http:
            response = http.get(
                OPENALEX_WORKS_URL,
                params={
                    "search": query,
                    "per_page": max(1, min(candidate_limit, 25)),
                    "sort": "relevance_score:desc",
                    "api_key": api_key,
                },
            )
    except httpx.TimeoutException as exc:
        raise SearchProviderError("OpenAlex", "timeout") from exc
    except httpx.HTTPError as exc:
        raise SearchProviderError("OpenAlex", "network_error") from exc

    _raise_for_provider(response, "OpenAlex")
    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError("OpenAlex", "invalid_json_response") from exc

    results: List[Dict[str, Any]] = []
    for index, item in enumerate((data.get("results") or [])[:candidate_limit]):
        if not isinstance(item, dict) or item.get("is_retracted"):
            continue
        title = str(item.get("display_name") or item.get("title") or "").strip()
        url = str(item.get("doi") or item.get("id") or "").strip()
        if not title or not url:
            continue
        try:
            safe_url = validate_public_http_url(url)
        except ValueError:
            continue
        authors = [
            str((authorship.get("author") or {}).get("display_name") or "").strip()
            for authorship in (item.get("authorships") or [])[:5]
            if isinstance(authorship, dict)
        ]
        authors = [value for value in authors if value]
        source = str(
            (((item.get("primary_location") or {}).get("source") or {}).get(
                "display_name"
            ))
            or ""
        ).strip()
        date = str(item.get("publication_date") or "").strip()
        abstract = _openalex_abstract(item.get("abstract_inverted_index"))
        parts = [
            f"Publication scientifique : {title}.",
            f"Date : {date}." if date else "",
            f"Auteurs : {', '.join(authors)}." if authors else "",
            f"Revue ou dépôt : {source}." if source else "",
            abstract,
        ]
        cited_by = item.get("cited_by_count")
        citation_bonus = (
            min(0.08, math.log10(max(1, int(cited_by))) * 0.02)
            if isinstance(cited_by, int)
            else 0.0
        )
        results.append(
            {
                "title": title,
                "snippet": " ".join(part for part in parts if part)[:3_600],
                "url": safe_url,
                "engine": "OpenAlex",
                "engine_score": max(
                    0.52,
                    min(0.94, 0.87 - index * 0.035 + citation_bonus),
                ),
                "evidence_kind": "structured_api",
            }
        )
    return results


def search_wikipedia(
    query: str,
    candidate_limit: int,
    *,
    timeout: float = 5.0,
) -> List[Dict[str, Any]]:
    """Retrieve compact French Wikipedia introductions for stable facts."""
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(3.0, timeout)),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "Lasme-LLM/0.8 (local research assistant)"},
        ) as http:
            response = http.get(
                WIKIPEDIA_API_URL,
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": query,
                    "gsrnamespace": 0,
                    "gsrlimit": max(1, min(candidate_limit, 10)),
                    "prop": "extracts|info",
                    "exintro": 1,
                    "explaintext": 1,
                    "inprop": "url",
                    "format": "json",
                    "formatversion": 2,
                    "origin": "*",
                },
            )
    except httpx.TimeoutException as exc:
        raise SearchProviderError("Wikimedia", "timeout") from exc
    except httpx.HTTPError as exc:
        raise SearchProviderError("Wikimedia", "network_error") from exc

    _raise_for_provider(response, "Wikimedia")
    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError("Wikimedia", "invalid_json_response") from exc

    pages = ((data.get("query") or {}).get("pages") or [])
    pages = sorted(
        (item for item in pages if isinstance(item, dict)),
        key=lambda item: int(item.get("index") or 10_000),
    )
    results: List[Dict[str, Any]] = []
    for index, item in enumerate(pages[:candidate_limit]):
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("extract") or "").strip()
        url = str(item.get("fullurl") or "").strip()
        if not title or not snippet or not url:
            continue
        try:
            safe_url = validate_public_http_url(url)
        except ValueError:
            continue
        results.append(
            {
                "title": title,
                "snippet": snippet[:3_600],
                "url": safe_url,
                "engine": "Wikimedia",
                "engine_score": max(0.48, 0.84 - index * 0.05),
                "evidence_kind": "structured_api",
            }
        )
    return results
