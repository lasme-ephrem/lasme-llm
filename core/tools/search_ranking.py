from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


FRENCH_STOPWORDS = {
    "a", "ai", "au", "aux", "avec", "ce", "ces", "dans", "de", "des",
    "du", "elle", "en", "et", "est", "il", "la", "le", "les", "leur",
    "leurs", "mais", "ou", "par", "pas", "pour", "que", "qui", "sa",
    "se", "ses", "son", "sur", "un", "une",
}
ENGLISH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "was", "what", "when", "where", "which", "who", "why", "with",
}
QUESTION_FILLERS = {
    "comment", "donne", "expliquer", "explique", "peux", "pourquoi",
    "quel", "quelle", "quelles", "quels", "trouve", "verifie",
}
STOPWORDS = FRENCH_STOPWORDS | ENGLISH_STOPWORDS | QUESTION_FILLERS

COMPLEX_MARKERS = {
    "analyse", "compare", "comparaison", "controverse", "difference",
    "differents", "enjeux", "evalue", "evolution", "impact", "impacts",
    "limites", "perspectives", "pourquoi", "rapport", "synthese",
}
TEMPORAL_MARKERS = {
    "actuel", "actuelle", "actualite", "aujourd", "dernier", "derniere",
    "maintenant", "nouveau", "nouvelle", "recent", "recente", "score",
    "version",
}
WINNER_MARKERS = {
    "champion", "champions", "gagne", "gagnant", "vainqueur", "winner",
    "winners", "won",
}
VERSION_MARKERS = {
    "release", "stable", "version",
}
TRUSTED_DOMAIN_SUFFIXES = (
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "europa.eu",
    "gov.uk",
    "lemonde.fr",
    "nasa.gov",
    "nature.com",
    "reuters.com",
    "science.org",
    "un.org",
    "who.int",
)
TRACKING_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "mc_",
)


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def search_terms(value: str) -> set[str]:
    return {
        term
        for term in normalize_search_text(value).split()
        if (len(term) >= 2 or term.isdigit()) and term not in STOPWORDS
    }


def hostname_for_url(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def source_family(hostname: str) -> str:
    """Group subdomains so docs.example.org and example.org are one source."""
    parts = hostname.casefold().split(".")
    if len(parts) <= 2:
        return hostname.casefold()
    compound_suffixes = {
        "ac.uk", "co.uk", "com.au", "com.br", "com.cn", "com.mx",
        "com.tr", "com.tw", "gov.uk", "org.uk",
    }
    suffix = ".".join(parts[-2:])
    width = 3 if suffix in compound_suffixes else 2
    return ".".join(parts[-width:])


def canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not key.casefold().startswith(TRACKING_QUERY_PREFIXES)
            ]
        )
        return urlunparse(
            (
                parsed.scheme.casefold(),
                (parsed.hostname or "").casefold().removeprefix("www."),
                parsed.path.rstrip("/") or "/",
                "",
                query,
                "",
            )
        )
    except ValueError:
        return url.strip()


def domain_matches(hostname: str, domains: Sequence[str]) -> bool:
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in domains
    )


def _authority_score(hostname: str, official_domains: Sequence[str]) -> float:
    if domain_matches(hostname, official_domains):
        first_label = hostname.split(".", 1)[0]
        if first_label in {
            "answers", "community", "discuss", "discussion", "forum", "forums",
        }:
            return 0.58
        return 1.0
    if hostname.endswith((".gov", ".gov.fr", ".edu", ".ac.uk")):
        return 0.92
    if domain_matches(hostname, TRUSTED_DOMAIN_SUFFIXES):
        return 0.82
    if hostname.startswith(("docs.", "developer.", "support.")):
        return 0.68
    return 0.42


def _freshness_score(text: str, query_terms: set[str]) -> float:
    if not query_terms.intersection(TEMPORAL_MARKERS):
        return 0.5
    current_year = datetime.date.today().year
    years = {int(year) for year in re.findall(r"\b20\d{2}\b", text)}
    if current_year in years:
        return 1.0
    if current_year - 1 in years:
        return 0.72
    if years:
        return 0.3
    return 0.45


def _answerability_score(
    title: str,
    snippet: str,
    query: str,
    coverage: float,
) -> float:
    """Estimate whether the excerpt contains an answer, not merely the topic."""
    query_tokens = search_terms(query)
    title_text = normalize_search_text(title)
    snippet_text = normalize_search_text(snippet)
    combined = f"{title_text} {snippet_text}"
    current_year = datetime.date.today().year

    if query_tokens.intersection(WINNER_MARKERS):
        direct_claim = bool(
            re.search(
                r"\b(crowned|claiming|claimed|won|victory|"
                r"remporte|remportee|sacre|sacree|gagne|gagnee|"
                r"campeon|campeona)\b",
                snippet_text,
            )
        )
        winner_word = bool(
            re.search(
                r"\b(champion|champions|winner|winners|vainqueur|vainqueurs)\b",
                snippet_text,
            )
        )
        final_word = bool(re.search(r"\b(final|finale)\b", snippet_text))
        current_result = str(current_year) in snippet_text
        archive_page = bool(
            re.search(r"\b(?:19|20)\d{2}\s+(?:19|20)\d{2}\b", title_text)
            or re.search(
                r"\b(history|historique|liste|palmares|winners from|"
                r"vainqueurs de)\b",
                title_text,
            )
        )
        score = (
            (0.55 if direct_claim else 0.0)
            + (0.15 if winner_word else 0.0)
            + (0.15 if final_word else 0.0)
            + (0.15 if current_result else 0.0)
            - (0.35 if archive_page and not direct_claim else 0.0)
        )
        return max(0.0, min(1.0, score))

    if query_tokens.intersection(VERSION_MARKERS):
        has_version_number = bool(
            re.search(r"\b\d{1,4}(?:\.\d{1,4}){1,3}\b", combined)
        )
        has_release_language = bool(
            re.search(
                r"\b(latest|stable|release|released|version|"
                r"derniere|disponible|sortie)\b",
                snippet_text,
            )
        )
        documentation_page = bool(
            re.search(r"\b(documentation|downloads?|release notes?)\b", combined)
        )
        score = (
            0.15 * coverage
            + (0.5 if has_version_number else 0.0)
            + (0.2 if has_release_language else 0.0)
            + (0.15 if documentation_page else 0.0)
        )
        return max(0.0, min(1.0, score))

    if query_tokens.intersection(TEMPORAL_MARKERS):
        has_current_year = str(current_year) in snippet_text
        has_direct_language = bool(
            re.search(
                r"\b(is|are|announced|confirmed|currently|"
                r"est|sont|annonce|confirme|actuellement)\b",
                snippet_text,
            )
        )
        return min(
            1.0,
            0.3
            + 0.35 * coverage
            + (0.2 if has_current_year else 0.0)
            + (0.15 if has_direct_language else 0.0),
        )

    return min(1.0, 0.45 + 0.45 * coverage)


def build_search_plan(
    query: str,
    official_domains: Sequence[str] = (),
    max_results: int | None = None,
) -> Dict[str, Any]:
    terms = search_terms(query)
    normalized_terms = set(normalize_search_text(query).split())
    complex_query = bool(normalized_terms.intersection(COMPLEX_MARKERS)) or len(terms) >= 10
    temporal_query = bool(normalized_terms.intersection(TEMPORAL_MARKERS))

    if complex_query:
        minimum, maximum, candidate_limit = 3, 6, 16
        scope = "complex"
    elif official_domains:
        minimum, maximum, candidate_limit = 1, 3, 10
        scope = "direct"
    else:
        minimum, maximum, candidate_limit = 2, 4, 12
        scope = "standard"

    if max_results is not None:
        maximum = max(1, min(maximum, max_results))
        minimum = min(minimum, maximum)

    return {
        "scope": scope,
        "minimum_sources": minimum,
        "maximum_sources": maximum,
        "candidate_limit": candidate_limit,
        "complex": complex_query,
        "temporal": temporal_query,
    }


def score_search_result(
    result: Dict[str, Any],
    query: str,
    official_domains: Sequence[str] = (),
    low_signal_domains: Sequence[str] = (),
) -> Dict[str, Any]:
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    url = str(result.get("url", "")).strip()
    hostname = hostname_for_url(url)
    query_tokens = search_terms(query)
    title_tokens = search_terms(title)
    content_tokens = search_terms(f"{title} {snippet}")

    coverage = (
        len(query_tokens.intersection(content_tokens)) / len(query_tokens)
        if query_tokens
        else 0.0
    )
    title_coverage = (
        len(query_tokens.intersection(title_tokens)) / len(query_tokens)
        if query_tokens
        else 0.0
    )
    engine_score = result.get("engine_score")
    if not isinstance(engine_score, (int, float)):
        engine_score = 0.52 if coverage else 0.35
    engine_score = max(0.0, min(1.0, float(engine_score)))

    authority = _authority_score(hostname, official_domains)
    freshness = _freshness_score(
        normalize_search_text(f"{title} {snippet}"),
        search_terms(query),
    )
    answerability = _answerability_score(
        title,
        snippet,
        query,
        coverage,
    )
    low_signal = domain_matches(hostname, low_signal_domains)
    exact_phrase = normalize_search_text(query) in normalize_search_text(
        f"{title} {snippet}"
    )

    score = (
        0.25 * engine_score
        + 0.22 * coverage
        + 0.12 * title_coverage
        + 0.16 * authority
        + 0.05 * freshness
        + 0.20 * answerability
        + (0.03 if exact_phrase else 0.0)
        - (0.28 if low_signal else 0.0)
    )
    score = max(0.0, min(1.0, score))

    ranked = dict(result)
    ranked.update(
        {
            "hostname": hostname,
            "source_family": source_family(hostname),
            "score": round(score, 4),
            "coverage": round(coverage, 4),
            "authority_score": round(authority, 4),
            "answerability_score": round(answerability, 4),
            "quality": (
                "official"
                if authority >= 0.99
                else "trusted"
                if authority >= 0.8
                else "standard"
            ),
        }
    )
    return ranked


def rank_candidates(
    results: Iterable[Dict[str, Any]],
    query: str,
    official_domains: Sequence[str] = (),
    low_signal_domains: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    deduplicated: Dict[str, Dict[str, Any]] = {}
    seen_titles: set[str] = set()

    for result in results:
        if not result.get("title") or not result.get("snippet") or not result.get("url"):
            continue
        key = canonical_url(str(result["url"]))
        normalized_title = normalize_search_text(str(result["title"]))
        if key in deduplicated or (normalized_title and normalized_title in seen_titles):
            existing = deduplicated.get(key)
            if existing and result.get("engine") not in str(existing.get("engine", "")):
                existing["engine"] = f"{existing.get('engine')} + {result.get('engine')}"
            continue
        ranked = score_search_result(
            result,
            query,
            official_domains=official_domains,
            low_signal_domains=low_signal_domains,
        )
        deduplicated[key] = ranked
        if normalized_title:
            seen_titles.add(normalized_title)

    return sorted(
        deduplicated.values(),
        key=lambda item: (
            float(item.get("score", 0.0)),
            float(item.get("authority_score", 0.0)),
            float(item.get("coverage", 0.0)),
        ),
        reverse=True,
    )


def _evidence_metrics(
    selected: Sequence[Dict[str, Any]],
    query: str,
) -> Dict[str, Any]:
    query_tokens = search_terms(query)
    covered_terms: set[str] = set()
    domains: set[str] = set()
    for item in selected:
        covered_terms.update(
            query_tokens.intersection(
                search_terms(f"{item.get('title', '')} {item.get('snippet', '')}")
            )
        )
        family = str(item.get("source_family", ""))
        if family:
            domains.add(family)

    coverage = len(covered_terms) / len(query_tokens) if query_tokens else 0.0
    average_score = (
        sum(float(item.get("score", 0.0)) for item in selected) / len(selected)
        if selected
        else 0.0
    )
    authority = max(
        (float(item.get("authority_score", 0.0)) for item in selected),
        default=0.0,
    )
    answerability = max(
        (float(item.get("answerability_score", 0.0)) for item in selected),
        default=0.0,
    )
    diversity = min(1.0, len(domains) / max(1, min(3, len(selected))))
    evidence_strength = (
        0.35 * average_score
        + 0.20 * coverage
        + 0.20 * authority
        + 0.15 * answerability
        + 0.10 * diversity
    )
    return {
        "coverage": round(coverage, 4),
        "average_score": round(average_score, 4),
        "authority": round(authority, 4),
        "answerability": round(answerability, 4),
        "independent_domains": len(domains),
        "evidence_strength": round(min(1.0, evidence_strength), 4),
    }


def adaptive_select_results(
    results: Iterable[Dict[str, Any]],
    query: str,
    official_domains: Sequence[str] = (),
    low_signal_domains: Sequence[str] = (),
    max_results: int | None = None,
) -> Dict[str, Any]:
    plan = build_search_plan(query, official_domains, max_results=max_results)
    ranked = rank_candidates(
        results,
        query,
        official_domains=official_domains,
        low_signal_domains=low_signal_domains,
    )
    total_candidate_count = len(ranked)
    if plan["scope"] == "direct":
        answerable_candidates = [
            item
            for item in ranked
            if float(item.get("answerability_score", 0.0)) >= 0.58
        ]
        # When a direct answer exists, exclude topical archives and generic
        # landing pages instead of letting lexical overlap confuse the model.
        if answerable_candidates:
            ranked = answerable_candidates
    remaining = list(ranked)
    selected: List[Dict[str, Any]] = []
    used_domains: set[str] = set()
    covered_terms: set[str] = set()
    query_tokens = search_terms(query)
    stop_reason = "no_relevant_source"
    sufficient = False

    while remaining and len(selected) < plan["maximum_sources"]:
        def marginal_score(item: Dict[str, Any]) -> float:
            item_terms = search_terms(
                f"{item.get('title', '')} {item.get('snippet', '')}"
            )
            new_coverage = len(
                query_tokens.intersection(item_terms) - covered_terms
            ) / max(1, len(query_tokens))
            repeated_domain = item.get("source_family") in used_domains
            return (
                float(item.get("score", 0.0))
                + 0.10 * new_coverage
                - (0.10 if repeated_domain else 0.0)
            )

        best = max(remaining, key=marginal_score)
        remaining.remove(best)
        has_direct_authoritative_answer = (
            best.get("quality") == "official"
            and float(best.get("answerability_score", 0.0)) >= 0.58
        )
        if (
            float(best.get("score", 0.0)) < 0.2
            or (
                float(best.get("coverage", 0.0)) < 0.12
                and not has_direct_authoritative_answer
            )
        ):
            break
        selected.append(best)
        family = str(best.get("source_family", ""))
        if family:
            used_domains.add(family)
        covered_terms.update(
            query_tokens.intersection(
                search_terms(f"{best.get('title', '')} {best.get('snippet', '')}")
            )
        )

        metrics = _evidence_metrics(selected, query)
        has_official = any(item.get("quality") == "official" for item in selected)
        if (
            plan["scope"] == "direct"
            and has_official
            and metrics["average_score"] >= 0.48
            and metrics["answerability"] >= 0.58
        ):
            sufficient = True
            stop_reason = "authoritative_source_found"
            break
        if (
            len(selected) >= plan["minimum_sources"]
            and metrics["coverage"] >= 0.5
            and metrics["average_score"] >= 0.42
            and metrics["answerability"] >= 0.5
            and (
                not plan["temporal"]
                or metrics["authority"] >= 0.62
            )
            and (
                metrics["independent_domains"] >= min(2, plan["minimum_sources"])
                or has_official
            )
        ):
            sufficient = True
            stop_reason = "sufficient_independent_evidence"
            break

    metrics = _evidence_metrics(selected, query)
    if not sufficient and len(selected) >= plan["maximum_sources"]:
        stop_reason = "source_budget_reached"
    elif not sufficient and selected:
        stop_reason = "insufficient_evidence"

    public_results = []
    for item in selected:
        public_results.append(
            {
                key: value
                for key, value in item.items()
                if key not in {
                    "engine_score",
                    "coverage",
                    "authority_score",
                    "answerability_score",
                    "hostname",
                    "source_family",
                }
            }
        )

    return {
        "results": public_results,
        "ranked_results": ranked,
        "strategy": {
            **plan,
            **metrics,
            "candidate_count": total_candidate_count,
            "answerable_candidate_count": len(ranked),
            "selected_count": len(selected),
            "sufficient": sufficient,
            "stop_reason": stop_reason,
        },
    }
