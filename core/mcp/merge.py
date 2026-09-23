"""Fusion des hits MCP : parse, URL canonique, score, dédup."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TITLE_LIMIT = 140
_SNIPPET_LIMIT = 500
_EXTRA_ENGINE = 1.4
_DOMAIN_BONUS = 2.0
_DOMAIN_MALUS = 4.0
_PER_DOMAIN = 2

_JSON_ENGINES = {"wikipedia", "sports", "weather", "hackernews"}
_STOPWORDS = {
    "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle",
    "en", "et", "est", "il", "la", "le", "les", "leur", "mais", "ou",
    "par", "pas", "pour", "que", "qui", "sa", "se", "son", "sur", "un",
    "une", "the", "and", "for", "are", "was", "with", "from", "that",
    "this", "you",
}
_MULTI_SUFFIXES = {
    "ac.uk", "co.uk", "com.au", "com.br", "co.jp", "com.mx", "gov.uk",
    "gouv.fr", "org.uk",
}
_INTENT_DOMAINS: dict[str, tuple[str, ...]] = {
    "knowledge": ("wikipedia.org",),
    "academic": ("arxiv.org",),
    "sports": ("lequipe.fr", "espn.com", "fifa.com", "uefa.com", "nba.com"),
    "news": (
        "reuters.com",
        "bbc.com",
        "bbc.co.uk",
        "lemonde.fr",
        "france24.com",
        "theguardian.com",
        "apnews.com",
    ),
    "code": ("developer.mozilla.org", "readthedocs.io", "readthedocs.org"),
    "finance": ("bloomberg.com", "ft.com", "coindesk.com"),
}
_SINK_LABELS = {"pinterest", "facebook", "quora"}
_SINK_DOMAINS = ("pinterest.com", "facebook.com", "fb.com", "quora.com")
_GAMBLE_PARTS = (
    "unibet",
    "parions",
    "betclic",
    "betfair",
    "bet365",
    "betway",
    "parissport",
)

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"https?://[^\s<>\]\)\"']+")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    engine: str
    published: str = ""


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(
        char for char in folded if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _terms(text: str) -> set[str]:
    return {
        term
        for term in _fold(text).split()
        if len(term) >= 2 and term not in _STOPWORDS
    }


def _clip(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean[:limit]


def _acceptable_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or any(char.isspace() for char in url):
        return ""
    lowered = url.lower()
    if lowered.startswith(("javascript:", "data:")):
        return ""
    if not lowered.startswith(("http://", "https://")):
        return ""
    return url


def canonical_url(url: str) -> str:
    """https, sans www, sans utm_*, sans slash final."""
    raw = (url or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith(("javascript:", "data:")):
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    if ":" in host:
        netloc = f"[{host}]"
    else:
        netloc = host
    port = parsed.port
    if port and port not in {80, 443}:
        netloc = f"{netloc}:{port}"
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(
        (
            "https",
            netloc,
            parsed.path.rstrip("/"),
            "",
            urlencode(pairs),
            "",
        )
    )


def _hostname(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        return host[4:]
    return host


def _host_is(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _site(hostname: str) -> str:
    if not hostname:
        return ""
    parts = hostname.split(".")
    if len(parts) <= 2:
        return hostname
    last_two = ".".join(parts[-2:])
    if last_two in _MULTI_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last_two


def _domain_bonus(hostname: str, intent: str) -> float:
    if not hostname:
        return 0.0
    if intent == "code" and hostname.startswith("docs."):
        return _DOMAIN_BONUS
    for domain in _INTENT_DOMAINS.get(intent, ()):
        if _host_is(hostname, domain):
            return _DOMAIN_BONUS
    return 0.0


def _domain_malus(hostname: str) -> float:
    if not hostname:
        return 0.0
    labels = re.split(r"[.\-]", hostname)
    if any(label in _SINK_LABELS for label in labels):
        return _DOMAIN_MALUS
    if any(_host_is(hostname, domain) for domain in _SINK_DOMAINS):
        return _DOMAIN_MALUS
    for label in labels:
        if label in {"bet", "bets", "betting", "cotes"}:
            return _DOMAIN_MALUS
        if any(part in label for part in _GAMBLE_PARTS):
            return _DOMAIN_MALUS
        if "cotes" in label:
            return _DOMAIN_MALUS
        if len(label) > 3 and label.startswith("bet") and label[3].isdigit():
            return _DOMAIN_MALUS
    return 0.0


def _score(hit: SearchHit, query_terms: set[str], intent: str) -> float:
    engines = [part for part in (hit.engine or "").split("+") if part]
    score = _EXTRA_ENGINE * max(0, len(engines) - 1)
    title_terms = _terms(hit.title)
    snippet_terms = _terms(hit.snippet)
    score += 2 * len(query_terms & title_terms)
    score += len(query_terms & snippet_terms)
    hostname = _hostname(hit.url)
    score += _domain_bonus(hostname, intent)
    score -= _domain_malus(hostname)
    return score


def _engine_of(node: dict[str, Any], fallback: str) -> str:
    for key in ("engine", "source", "provider"):
        raw = node.get(key)
        if not isinstance(raw, str):
            continue
        token = re.sub(r"[^a-z]", "", raw.lower())
        if token in _JSON_ENGINES:
            return token
    return fallback


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_text_value(item) for item in value]
        return " ".join(part for part in parts if part)
    return ""


def _first_text(node: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _text_value(node.get(key))
        if text:
            return text
    return ""


def _collect(node: Any, engine: str, hits: list[SearchHit]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect(item, engine, hits)
        return
    if not isinstance(node, dict):
        return
    engine = _engine_of(node, engine)
    url = ""
    for key in ("url", "link", "href"):
        url = _acceptable_url(node.get(key))
        if url:
            break
    title = _first_text(node, ("title", "name"))
    if url and title:
        hits.append(
            SearchHit(
                title=title[:300],
                url=url,
                snippet=_first_text(
                    node, ("snippet", "description", "content", "extract")
                )[:2000],
                engine=engine,
                published=_first_text(node, ("published", "published_at", "date")),
            )
        )
    for value in node.values():
        if isinstance(value, (dict, list)):
            _collect(value, engine, hits)


def _json_value(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(
            r"^```(?:json)?\s*", "", stripped, count=1, flags=re.IGNORECASE
        )
        stripped = re.sub(r"\s*```$", "", stripped)
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _loose_hits(text: str, engine: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    occupied: list[tuple[int, int]] = []
    matches = list(_MD_LINK.finditer(text))
    for index, match in enumerate(matches):
        url = _acceptable_url(match.group(2))
        if not url:
            continue
        title = re.sub(r"\s+", " ", match.group(1)).strip() or url
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        snippet = re.sub(r"\s+", " ", text[match.end():end]).strip()[:1000]
        hits.append(SearchHit(title=title, url=url, snippet=snippet, engine=engine))
        occupied.append(match.span())
    seen = {canonical_url(hit.url) for hit in hits}
    for match in _BARE_URL.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        url = _acceptable_url(match.group(0).rstrip(".,;:"))
        if not url:
            continue
        key = canonical_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        hits.append(SearchHit(title=url, url=url, snippet="", engine=engine))
    return hits


def parse_mcp_payload(text: str, engine: str) -> list[SearchHit]:
    """JSON récursif, sinon liens markdown et URL nues."""
    raw = text or ""
    parsed = _json_value(raw)
    if parsed is not None:
        hits: list[SearchHit] = []
        _collect(parsed, engine or "", hits)
        return hits
    return _loose_hits(raw, engine or "")


def _join_engines(left: str, right: str) -> str:
    names: list[str] = []
    for part in f"{left}+{right}".split("+"):
        part = part.strip()
        if part and part not in names:
            names.append(part)
    return "+".join(names)


def _prefer_title(current: str, new: str, url: str) -> str:
    current = (current or "").strip()
    new = (new or "").strip()
    if not current or current == url:
        return new or current
    if not new or new == url:
        return current
    return current if len(current) >= len(new) else new


def merge_hits(
    groups: list[list[SearchHit]],
    query: str,
    intent: str,
    limit: int = 8,
) -> list[SearchHit]:
    """Dédup canonique, score, au plus 2 URL par domaine."""
    if limit <= 0:
        return []
    merged: dict[str, SearchHit] = {}
    order: list[str] = []
    for group in groups:
        for hit in group or []:
            url = _acceptable_url(hit.url)
            key = canonical_url(url)
            if not url or not key:
                continue
            current = merged.get(key)
            if current is None:
                merged[key] = SearchHit(
                    title=(hit.title or "").strip(),
                    url=key,
                    snippet=(hit.snippet or "").strip(),
                    engine=(hit.engine or "").strip(),
                    published=(hit.published or "").strip(),
                )
                order.append(key)
                continue
            current.engine = _join_engines(current.engine, hit.engine)
            current.title = _prefer_title(current.title, hit.title, key)
            incoming = (hit.snippet or "").strip()
            if len(incoming) > len(current.snippet or ""):
                current.snippet = incoming
            if not current.published and hit.published:
                current.published = hit.published.strip()

    query_terms = _terms(query)
    ranked = sorted(
        (
            (
                _score(merged[key], query_terms, intent),
                index,
                merged[key],
            )
            for index, key in enumerate(order)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    selected: list[SearchHit] = []
    deferred: list[SearchHit] = []
    per_domain: dict[str, int] = {}
    distinct = {_site(_hostname(hit.url)) for _score, _index, hit in ranked}
    for _score_value, _index, hit in ranked:
        domain = _site(_hostname(hit.url))
        if per_domain.get(domain, 0) >= _PER_DOMAIN:
            deferred.append(hit)
            continue
        per_domain[domain] = per_domain.get(domain, 0) + 1
        selected.append(hit)
        if len(selected) >= limit:
            break
    # Plafond levé seulement s'il n'y a pas d'autre domaine.
    if len(selected) < limit and len(distinct) < 2:
        for hit in deferred:
            selected.append(hit)
            if len(selected) >= limit:
                break
    return [
        SearchHit(
            title=_clip(hit.title, _TITLE_LIMIT) or "Sans titre",
            url=hit.url,
            snippet=_clip(hit.snippet, _SNIPPET_LIMIT),
            engine=hit.engine,
            published=hit.published,
        )
        for hit in selected
    ]
