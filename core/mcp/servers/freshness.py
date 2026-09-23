"""Serveur MCP stdio : Wikipédia, sports, météo et Hacker News, sans clé payante."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from html import unescape
from typing import Any, Callable
from urllib.parse import quote, urlencode

import httpx
from mcp.server.fastmcp import FastMCP

USER_AGENT = "LasmeLLM-freshness/1"
HTTP_TIMEOUT_S = 8.0
MAX_REDIRECTS = 5
THESPORTSDB_PUBLIC_KEY = "3"

_WIKI_LIMIT = 3
_HN_LIMIT = 5
_MAX_EVENTS = 10
_MAX_TEAMS = 5

_SPORTS_ROOT = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_PUBLIC_KEY}"
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_HN_URL = "https://hn.algolia.com/api/v1/search"
_FORECAST_FIELDS = {
    "current": "temperature_2m,weather_code,wind_speed_10m",
    "daily": "temperature_2m_max,temperature_2m_min",
    "timezone": "auto",
    "forecast_days": 3,
}

_WIKI_FAIL = "La recherche Wikipédia a échoué (réseau ou réponse invalide)."
_SPORTS_FAIL = "La recherche sportive a échoué (réseau ou réponse invalide)."
_WEATHER_FAIL = "La météo est indisponible (réseau ou réponse invalide)."
_HN_FAIL = "Les actualités techniques sont indisponibles (réseau ou réponse invalide)."
_WIKI_EMPTY = "Aucun article Wikipédia trouvé."
_SPORTS_EMPTY = "Aucun événement ni équipe trouvé sur TheSportsDB."
_WEATHER_EMPTY = "Lieu introuvable pour la météo."
_HN_EMPTY = "Aucune actualité Hacker News trouvée."
_PARTIAL_SPORTS = "Une source sportive n'a pas répondu."

_TAG_RE = re.compile(r"<[^>]+>")
_ACCENT_RE = re.compile(r"[àâäéèêëïîôùûüçœæ]", re.IGNORECASE)
_FRENCH_WORD_RE = re.compile(
    r"\b(?:le|la|les|des|une|un|et|ou|dans|pour|avec|sur|est|qui|que|quoi|"
    r"comment|pourquoi|quand|cette|cet|ces|du|de|au|aux|chez|aussi|mais|"
    r"tres|être|etre|sont|nous|vous|elles|demain|meteo|quel|quelle|quels|"
    r"quelles|aujourd'hui|hier)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_FR_LONG_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|février|mars|avril|mai|juin|juillet|"
    r"aout|août|septembre|octobre|novembre|decembre|décembre)\s+(\d{4})\b",
    re.IGNORECASE,
)
_RELATIVE_DAY_RE = re.compile(
    r"aujourd[\s']?hui|aujourdhui|\btoday\b|\bhier\b|\byesterday\b|"
    r"date du jour|\bce jour\b",
    re.IGNORECASE,
)
_MONTHS_FR = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}
_GENERIC_TOKENS = {
    "match",
    "matchs",
    "rencontre",
    "rencontres",
    "score",
    "scores",
    "resultat",
    "resultats",
    "résultat",
    "résultats",
    "foot",
    "football",
    "soccer",
    "basket",
    "basketball",
    "nba",
    "sport",
    "sports",
    "equipe",
    "équipe",
    "equipes",
    "équipes",
    "jeu",
    "jeux",
    "live",
    "direct",
    "aujourdhui",
    "aujourd",
    "hui",
    "hier",
    "today",
    "yesterday",
    "vs",
    "contre",
    "le",
    "la",
    "les",
    "de",
    "des",
    "du",
    "un",
    "une",
    "et",
    "ou",
    "au",
    "aux",
    "pour",
    "sur",
    "en",
    "the",
    "of",
    "and",
}
_WMO_FR = {
    0: "ciel clair",
    1: "peu nuageux",
    2: "partiellement nuageux",
    3: "nuageux",
    45: "brouillard",
    48: "brouillard givrant",
    51: "bruine faible",
    53: "bruine",
    55: "bruine forte",
    56: "bruine verglaçante faible",
    57: "bruine verglaçante forte",
    61: "pluie faible",
    63: "pluie",
    65: "pluie forte",
    66: "pluie verglaçante faible",
    67: "pluie verglaçante forte",
    71: "neige faible",
    73: "neige",
    75: "neige forte",
    77: "grains de neige",
    80: "averses de pluie faibles",
    81: "averses de pluie",
    82: "fortes averses de pluie",
    85: "averses de neige faibles",
    86: "fortes averses de neige",
    95: "orage",
    96: "orage avec grêle",
    99: "orage avec forte grêle",
}

mcp = FastMCP(
    "freshness",
    instructions=(
        "Fraîcheur sans clé payante : Wikipédia, sports (TheSportsDB), "
        "météo (Open-Meteo) et actualités techniques (Hacker News). "
        "Chaque outil renvoie un JSON UTF-8 {results, note}."
    ),
    log_level="ERROR",
)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _empty(note: str) -> dict[str, Any]:
    return {"results": [], "note": note}


def _guarded(fail_note: str, build: Callable[[], dict[str, Any]]) -> str:
    try:
        return _dump(build())
    except Exception:
        return _dump(_empty(fail_note))


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_S,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENT},
        trust_env=False,
    )


def _read_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("objet JSON attendu")
    return data


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _plain(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    text = unescape(_TAG_RE.sub("", str(value)))
    return " ".join(text.replace("\xa0", " ").split())


def _normalize(value: str) -> str:
    return value.casefold().replace("’", "'").replace("‘", "'").replace("`", "'")


def _text_arg(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()


def _fmt_num(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "n.d."
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw.casefold() == "null":
            return "n.d."
        try:
            value = float(raw)
        except ValueError:
            return raw
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _score_present(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        raw = value.strip()
        return bool(raw) and raw.casefold() != "null"
    return False


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _remember(found: list[date], value: date | None) -> None:
    if value is not None and value not in found:
        found.append(value)


def _parse_dates(query: str) -> list[date]:
    found: list[date] = []
    for match in _ISO_DATE_RE.finditer(query):
        _remember(
            found,
            _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3))),
        )
    for match in _DMY_DATE_RE.finditer(query):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        _remember(found, _safe_date(year, month, day) or _safe_date(year, day, month))
    normalized = _normalize(query)
    for match in _FR_LONG_DATE_RE.finditer(normalized):
        month = _MONTHS_FR.get(match.group(2).casefold())
        if month is None:
            continue
        _remember(found, _safe_date(int(match.group(3)), month, int(match.group(1))))
    return found


def _sports_dates(query: str, *, today: date | None = None) -> list[date]:
    current = today or date.today()
    text = _normalize(query)
    found: list[date] = []
    if re.search(r"aujourd[\s']?hui|aujourdhui|\btoday\b|date du jour|\bce jour\b", text):
        found.append(current)
    if re.search(r"\bhier\b|\byesterday\b", text):
        _remember(found, current - timedelta(days=1))
    for parsed in _parse_dates(query):
        if parsed == current:
            _remember(found, current)
    return found


def _sports_search_text(query: str, *, today: date | None = None) -> str:
    current = today or date.today()
    text = query.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = _RELATIVE_DAY_RE.sub(" ", text)
    for parsed in _sports_dates(query, today=current):
        text = text.replace(parsed.isoformat(), " ")
        text = re.sub(
            rf"\b0?{parsed.day}[./-]0?{parsed.month}[./-]{parsed.year}\b",
            " ",
            text,
        )
    return " ".join(text.split())


def _day_sports(query: str) -> list[str]:
    sports = ["Soccer"]
    if re.search(r"nba|basket", query, re.IGNORECASE):
        sports.append("Basketball")
    return sports


def _day_tokens(search_text: str) -> list[str]:
    raw = re.findall(
        r"[0-9a-zàâäéèêëïîôùûüçœæ]+(?:-[0-9a-zàâäéèêëïîôùûüçœæ]+)*",
        _normalize(search_text),
    )
    return [token for token in raw if len(token) > 1 and token not in _GENERIC_TOKENS]


def _filter_day_events(
    rows: list[dict[str, Any]],
    search_text: str,
) -> list[dict[str, Any]]:
    tokens = _day_tokens(search_text)
    if not tokens:
        return rows
    selected: list[dict[str, Any]] = []
    for row in rows:
        blob = " ".join(
            _plain(row.get(key))
            for key in (
                "strEvent",
                "strHomeTeam",
                "strAwayTeam",
                "strLeague",
                "strSport",
                "strFilename",
            )
        )
        folded = blob.casefold()
        if any(token in folded for token in tokens):
            selected.append(row)
    return selected


def _event_identity(event: dict[str, Any]) -> str:
    event_id = _plain(event.get("idEvent"))
    if event_id:
        return f"id:{event_id}"
    return "|".join(
        (
            _plain(event.get("strEvent")),
            _plain(event.get("dateEvent")),
            _plain(event.get("strHomeTeam")),
            _plain(event.get("strAwayTeam")),
        )
    )


def _event_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _dicts(payload)
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("event", "events"):
        rows.extend(_dicts(payload.get(key)))
    return rows


def _team_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _dicts(payload)
    if not isinstance(payload, dict):
        return []
    if payload.get("idTeam") or payload.get("strTeam"):
        teams = payload.get("teams")
        if not isinstance(teams, list):
            return [payload]
    return _dicts(payload.get("teams"))


def _event_url(event: dict[str, Any]) -> str:
    event_id = _plain(event.get("idEvent"))
    if event_id:
        return f"https://www.thesportsdb.com/event/{event_id}"
    video = event.get("strVideo")
    if isinstance(video, str) and video.startswith(("http://", "https://")):
        return video.strip()
    return "https://www.thesportsdb.com/"


def _team_url(team: dict[str, Any]) -> str:
    team_id = _plain(team.get("idTeam"))
    if team_id:
        return f"https://www.thesportsdb.com/team/{team_id}"
    return "https://www.thesportsdb.com/"


def _event_snippet(event: dict[str, Any]) -> str:
    home = _plain(event.get("strHomeTeam"))
    away = _plain(event.get("strAwayTeam"))
    home_score = event.get("intHomeScore")
    away_score = event.get("intAwayScore")
    if _score_present(home_score) and _score_present(away_score):
        score = f"score {_fmt_num(home_score)}-{_fmt_num(away_score)}"
    else:
        score = "score non communiqué"
    when = " ".join(
        part
        for part in (_plain(event.get("dateEvent")), _plain(event.get("strTime")))
        if part
    )
    teams = " contre ".join(part for part in (home, away) if part)
    league = _plain(event.get("strLeague"))
    return ", ".join(part for part in (score, when, teams, league) if part)


def _first_sentence(text: str, limit: int = 240) -> str:
    if not text:
        return ""
    end = text.find(". ")
    sentence = text[: end + 1] if 40 <= end <= limit else text
    if len(sentence) > limit:
        return sentence[: limit - 1].rstrip() + "..."
    return sentence


def _team_snippet(team: dict[str, Any]) -> str:
    head = ", ".join(
        part
        for part in (
            _plain(team.get("strSport")),
            _plain(team.get("strLeague")),
            _plain(team.get("strCountry")),
        )
        if part
    )
    sentence = _first_sentence(_plain(team.get("strDescriptionFR")))
    if head and sentence:
        return f"{head}. {sentence}"
    return head or sentence


def _wiki_language(query: str) -> str:
    text = _normalize(query)
    if _ACCENT_RE.search(text) or _FRENCH_WORD_RE.search(text):
        return "fr"
    return "en"


def _wiki_hits(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    query = payload.get("query")
    if not isinstance(query, dict):
        return []
    hits = [
        item for item in _dicts(query.get("search")) if _plain(item.get("title"))
    ]
    return hits[:_WIKI_LIMIT]


def _summary_items(summaries: Any) -> list[dict[str, Any]]:
    if isinstance(summaries, dict):
        if any(key in summaries for key in ("title", "extract", "content_urls", "lang")):
            return [summaries]
        return [item for item in summaries.values() if isinstance(item, dict)]
    return _dicts(summaries)


def _wiki_page_url(summary: dict[str, Any], title: str) -> str:
    content_urls = summary.get("content_urls")
    if isinstance(content_urls, dict):
        for channel in ("desktop", "mobile"):
            page = content_urls.get(channel)
            if isinstance(page, dict) and isinstance(page.get("page"), str):
                url = page["page"].strip()
                if url.startswith(("http://", "https://")):
                    return url
    lang = _plain(summary.get("lang"))
    if lang and title:
        slug = quote(title.replace(" ", "_"), safe="")
        return f"https://{lang}.wikipedia.org/wiki/{slug}"
    return ""


def _wiki_row(
    hit: dict[str, Any] | None,
    summary: dict[str, Any] | None,
) -> dict[str, str] | None:
    summary = summary or {}
    hit = hit or {}
    title = _plain(summary.get("title")) or _plain(hit.get("title"))
    url = _wiki_page_url(summary, title)
    snippet = _plain(summary.get("extract")) or _plain(hit.get("snippet"))
    if not title or not url:
        return None
    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "engine": "wikipedia",
    }


def _wmo_label(code: Any) -> str:
    if code is None or code == "":
        return ""
    try:
        number = int(float(code))
    except (TypeError, ValueError):
        return ""
    return _WMO_FR.get(number, "conditions non précisées")


def _place_from_geo(geo: Any) -> dict[str, Any] | None:
    if not isinstance(geo, dict):
        return None
    results = geo.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and _has_coords(item):
                return item
        return None
    if _has_coords(geo):
        return geo
    return None


def _has_coords(place: dict[str, Any]) -> bool:
    return place.get("latitude") is not None and place.get("longitude") is not None


def _lieu_label(place: dict[str, Any]) -> str:
    name = _plain(place.get("name"))
    country = _plain(place.get("country"))
    if name and country:
        return f"{name}, {country}"
    if name or country:
        return name or country
    return f"{place.get('latitude')}, {place.get('longitude')}"


def _forecast_url(latitude: Any, longitude: Any) -> str:
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "current": _FORECAST_FIELDS["current"],
        "daily": _FORECAST_FIELDS["daily"],
        "timezone": _FORECAST_FIELDS["timezone"],
        "forecast_days": _FORECAST_FIELDS["forecast_days"],
    }
    return f"{_FORECAST_URL}?{urlencode(params)}"


def _outlook(daily: dict[str, Any]) -> str:
    days = daily.get("time")
    if not isinstance(days, list):
        return ""
    highs = daily.get("temperature_2m_max")
    lows = daily.get("temperature_2m_min")
    if not isinstance(highs, list):
        highs = []
    if not isinstance(lows, list):
        lows = []
    chunks: list[str] = []
    for index, day in enumerate(days[:3]):
        if not isinstance(day, str) or not day:
            continue
        low = _fmt_num(lows[index]) if index < len(lows) else "n.d."
        high = _fmt_num(highs[index]) if index < len(highs) else "n.d."
        chunks.append(f"{day} min {low} °C, max {high} °C")
    return " ; ".join(chunks)


def _weather_body(current: dict[str, Any], daily: dict[str, Any]) -> str:
    parts: list[str] = []
    condition = _wmo_label(current.get("weather_code"))
    if condition:
        parts.append(condition)
    if "temperature_2m" in current and current.get("temperature_2m") is not None:
        parts.append(f"{_fmt_num(current.get('temperature_2m'))} °C")
    if "wind_speed_10m" in current and current.get("wind_speed_10m") is not None:
        parts.append(f"vent {_fmt_num(current.get('wind_speed_10m'))} km/h")
    head = ", ".join(parts)
    outlook = _outlook(daily)
    if head and outlook:
        text = f"{head}. Prévisions : {outlook}."
    elif head:
        text = f"{head}."
    elif outlook:
        text = f"Prévisions : {outlook}."
    else:
        text = "Prévision indisponible."
    return text[:1].upper() + text[1:]


def _hn_url(hit: dict[str, Any]) -> str:
    for key in ("url", "story_url"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    object_id = hit.get("objectID")
    if object_id is None or isinstance(object_id, bool):
        return ""
    text = str(object_id).strip()
    if not text:
        return ""
    return f"https://news.ycombinator.com/item?id={text}"


def _hn_snippet(hit: dict[str, Any], title: str) -> str:
    created = hit.get("created_at")
    day = ""
    if isinstance(created, str) and len(created) >= 10 and created[4:5] == "-":
        day = created[:10]
    parts = [f"{_fmt_num(hit.get('points'))} points"]
    if day:
        parts.append(day)
    if title:
        parts.append(title)
    return ", ".join(parts)


def format_wiki(search_payload: Any, summaries: Any) -> dict[str, Any]:
    """Jusqu'à 3 pages : URL canonique et extrait du résumé."""
    hits = _wiki_hits(search_payload)
    items = _summary_items(summaries)
    by_title: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _normalize(_plain(item.get("title")))
        if key and key not in by_title:
            by_title[key] = item
    results: list[dict[str, str]] = []
    if hits:
        pairs = hits[:_WIKI_LIMIT]
        for index, hit in enumerate(pairs):
            key = _normalize(_plain(hit.get("title")))
            summary = by_title.get(key)
            if summary is None and index < len(items):
                summary = items[index]
            row = _wiki_row(hit, summary)
            if row is not None:
                results.append(row)
    else:
        for item in items[:_WIKI_LIMIT]:
            row = _wiki_row(None, item)
            if row is not None:
                results.append(row)
    if not results:
        return _empty(_WIKI_EMPTY)
    return {"results": results, "note": ""}


def format_sports(events_payload: Any, teams_payload: Any) -> dict[str, Any]:
    """Événements puis équipes : score, date, équipes, ligue."""
    results: list[dict[str, str]] = []
    seen_events: set[str] = set()
    for event in _event_rows(events_payload):
        home = _plain(event.get("strHomeTeam"))
        away = _plain(event.get("strAwayTeam"))
        title = _plain(event.get("strEvent")) or " contre ".join(
            part for part in (home, away) if part
        )
        identity = _event_identity(event)
        if not title or identity in seen_events:
            continue
        seen_events.add(identity)
        results.append(
            {
                "title": title,
                "url": _event_url(event),
                "snippet": _event_snippet(event),
                "engine": "sports",
            }
        )
    seen_teams: set[str] = set()
    for team in _team_rows(teams_payload):
        name = _plain(team.get("strTeam"))
        if not name:
            continue
        identity = _plain(team.get("idTeam")) or name.casefold()
        if identity in seen_teams:
            continue
        seen_teams.add(identity)
        results.append(
            {
                "title": name,
                "url": _team_url(team),
                "snippet": _team_snippet(team),
                "engine": "sports",
            }
        )
    if not results:
        return _empty(_SPORTS_EMPTY)
    return {"results": results, "note": ""}


def format_weather(geo: Any, forecast: Any) -> dict[str, Any]:
    """Météo lisible en français à partir du géocodage et de la prévision."""
    place = _place_from_geo(geo)
    if place is None:
        return _empty(_WEATHER_EMPTY)
    lieu = _lieu_label(place)
    short = _plain(place.get("name")) or lieu
    data = forecast if isinstance(forecast, dict) else {}
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
    body = _weather_body(current, daily)
    if lieu:
        snippet = f"À {lieu} : {body[:1].lower()}{body[1:]}"
    else:
        snippet = body
    return {
        "results": [
            {
                "title": f"Météo à {short}" if short else "Météo",
                "url": _forecast_url(place.get("latitude"), place.get("longitude")),
                "snippet": snippet,
                "engine": "weather",
            }
        ],
        "note": "",
    }


def format_hn(payload: Any) -> dict[str, Any]:
    """Cinq articles Hacker News au plus : points, date, titre."""
    hits = _dicts(payload.get("hits")) if isinstance(payload, dict) else []
    results: list[dict[str, str]] = []
    for hit in hits:
        if len(results) >= _HN_LIMIT:
            break
        title = _plain(hit.get("title") or hit.get("story_title"))
        url = _hn_url(hit)
        if not title or not url:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": _hn_snippet(hit, title),
                "engine": "hackernews",
            }
        )
    if not results:
        return _empty(_HN_EMPTY)
    return {"results": results, "note": ""}


def _summary_for(
    client: httpx.Client,
    lang: str,
    title: str,
    hit: dict[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    try:
        slug = quote(title.replace(" ", "_"), safe="")
        summary = _read_json(
            client,
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}",
        )
    except Exception:
        summary = {}
    if not summary:
        return {
            "title": title,
            "lang": lang,
            "extract": _plain(hit.get("snippet")),
        }
    summary.setdefault("lang", lang)
    if not _plain(summary.get("extract")):
        summary["extract"] = _plain(hit.get("snippet"))
    return summary


def _wiki_bundle(
    client: httpx.Client,
    lang: str,
    query: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _read_json(
        client,
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": _WIKI_LIMIT,
            "format": "json",
            "utf8": 1,
        },
    )
    summaries = [
        _summary_for(client, lang, _plain(hit.get("title")), hit)
        for hit in _wiki_hits(payload)
    ]
    return payload, summaries


def _wiki_lookup_payload(query: Any) -> dict[str, Any]:
    text = _text_arg(query)
    if text is None:
        return _empty("Requête Wikipédia invalide.")
    if not text:
        return _empty("Requête Wikipédia vide.")
    primary = _wiki_language(text)
    secondary = "en" if primary == "fr" else "fr"
    search_payload: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    saw_response = False
    with _client() as client:
        try:
            search_payload, summaries = _wiki_bundle(client, primary, text)
            saw_response = True
        except Exception:
            search_payload, summaries = {}, []
        if not _wiki_hits(search_payload):
            try:
                search_payload, summaries = _wiki_bundle(client, secondary, text)
                saw_response = True
            except Exception:
                if not saw_response:
                    raise
    return format_wiki(search_payload, summaries)


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        identity = _event_identity(event)
        if identity in seen:
            continue
        seen.add(identity)
        chosen.append(event)
    return chosen


def _sports_lookup_payload(query: Any) -> dict[str, Any]:
    text = _text_arg(query)
    if text is None:
        return _empty("Requête sportive invalide.")
    if not text:
        return _empty("Requête sportive vide.")
    current = date.today()
    search_text = _sports_search_text(text, today=current)
    days = _sports_dates(text, today=current)
    if days and not _day_tokens(search_text):
        search_text = ""
    if not search_text and not days:
        return format_sports(None, None)
    events: list[dict[str, Any]] = []
    teams: list[dict[str, Any]] = []
    ok = False
    errors = False
    with _client() as client:
        if search_text:
            param = "_".join(search_text.split())
            try:
                found = _read_json(
                    client,
                    f"{_SPORTS_ROOT}/searchevents.php",
                    {"e": param},
                )
                ok = True
                events.extend(_dicts(found.get("event")))
            except Exception:
                errors = True
            try:
                found = _read_json(
                    client,
                    f"{_SPORTS_ROOT}/searchteams.php",
                    {"t": param},
                )
                ok = True
                teams.extend(_dicts(found.get("teams")))
            except Exception:
                errors = True
        for day in days:
            for sport in _day_sports(text):
                try:
                    found = _read_json(
                        client,
                        f"{_SPORTS_ROOT}/eventsday.php",
                        {"d": day.isoformat(), "s": sport},
                    )
                    ok = True
                    rows = _dicts(found.get("events")) or _dicts(found.get("event"))
                    events.extend(_filter_day_events(rows, search_text))
                except Exception:
                    errors = True
    if not ok:
        return _empty(_SPORTS_FAIL if errors else _SPORTS_EMPTY)
    trimmed_teams: list[dict[str, Any]] = []
    seen_teams: set[str] = set()
    for team in teams:
        identity = _plain(team.get("idTeam")) or _plain(team.get("strTeam")).casefold()
        if not identity or identity in seen_teams:
            continue
        seen_teams.add(identity)
        trimmed_teams.append(team)
        if len(trimmed_teams) >= _MAX_TEAMS:
            break
    formatted = format_sports(
        {"event": _dedupe_events(events)[:_MAX_EVENTS]},
        {"teams": trimmed_teams},
    )
    if errors and not formatted["results"]:
        return _empty(_SPORTS_FAIL)
    if errors and not formatted["note"]:
        formatted["note"] = _PARTIAL_SPORTS
    return formatted


def _weather_lookup_payload(place: Any) -> dict[str, Any]:
    text = _text_arg(place)
    if text is None:
        return _empty("Lieu météo invalide.")
    if not text:
        return _empty("Lieu météo vide.")
    with _client() as client:
        geo = _read_json(
            client,
            _GEO_URL,
            {"name": text, "count": 1, "language": "fr", "format": "json"},
        )
        located = _place_from_geo(geo)
        if located is None:
            return format_weather(geo, {})
        try:
            forecast = _read_json(
                client,
                _FORECAST_URL,
                {
                    "latitude": located.get("latitude"),
                    "longitude": located.get("longitude"),
                    "current": _FORECAST_FIELDS["current"],
                    "daily": _FORECAST_FIELDS["daily"],
                    "timezone": _FORECAST_FIELDS["timezone"],
                    "forecast_days": _FORECAST_FIELDS["forecast_days"],
                },
            )
        except Exception:
            forecast = {}
    return format_weather(geo, forecast)


def _hn_lookup_payload(query: Any) -> dict[str, Any]:
    text = _text_arg(query)
    if text is None:
        return _empty("Requête d'actualités invalide.")
    with _client() as client:
        payload = _read_json(
            client,
            _HN_URL,
            {"tags": "story", "hitsPerPage": _HN_LIMIT, "query": text},
        )
    return format_hn(payload)


@mcp.tool(structured_output=False)
def sports_lookup(query: str) -> str:
    """Équipes et matchs TheSportsDB. Aujourd'hui ou hier : rencontres du jour."""
    return _guarded(_SPORTS_FAIL, lambda: _sports_lookup_payload(query))


@mcp.tool(structured_output=False)
def weather_lookup(place: str) -> str:
    """Météo actuelle et prévisions à 3 jours pour un lieu (Open-Meteo)."""
    return _guarded(_WEATHER_FAIL, lambda: _weather_lookup_payload(place))


@mcp.tool(structured_output=False)
def tech_news(query: str) -> str:
    """Cinq actualités techniques Hacker News pour une requête."""
    return _guarded(_HN_FAIL, lambda: _hn_lookup_payload(query))


@mcp.tool(structured_output=False)
def wiki_lookup(query: str) -> str:
    """Jusqu'à 3 pages Wikipédia (français si la requête l'est, sinon anglais)."""
    return _guarded(_WIKI_FAIL, lambda: _wiki_lookup_payload(query))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
