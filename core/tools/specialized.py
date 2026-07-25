from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx


WEATHER_MARKERS = (
    "meteo",
    "météo",
    "temperature",
    "température",
    "weather",
)
FINANCE_MARKERS = (
    "action",
    "bourse",
    "cours",
    "stock",
    "prix",
)
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"}


def detect_specialized_request(query: str) -> Optional[Dict[str, str]]:
    text = " ".join((query or "").split())
    lowered = text.casefold()
    if any(marker in lowered for marker in WEATHER_MARKERS):
        matches = re.findall(
            r"\b(?:à|a|pour|in)\s+"
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,60}?)(?=\s+(?:demain|aujourd'hui|ce soir)\b|[?!.]|$)",
            text,
            flags=re.IGNORECASE,
        )
        location = (matches[-1] if matches else "").strip(" ?.!,")
        if location:
            return {"type": "weather", "location": location}

    symbol_match = re.search(r"(?:\$|\b)([A-Z]{2,5})(?:\b)", text)
    symbol = symbol_match.group(1) if symbol_match else ""
    if symbol in CRYPTO_SYMBOLS and (
        "crypto" in lowered or "bitcoin" in lowered or "ethereum" in lowered
        or any(marker in lowered for marker in FINANCE_MARKERS)
    ):
        return {"type": "crypto", "symbol": symbol}
    if symbol and any(marker in lowered for marker in FINANCE_MARKERS):
        return {"type": "stock", "symbol": symbol}
    return None


def _weather_result(location: str, timeout: int) -> Dict[str, Any]:
    with httpx.Client(timeout=timeout, trust_env=False) as http:
        geocode = http.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "fr", "format": "json"},
        )
        geocode.raise_for_status()
        places = geocode.json().get("results") or []
        if not places:
            return {"status": "unavailable", "type": "weather", "results": []}
        place = places[0]
        forecast = http.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": (
                    "temperature_2m,apparent_temperature,precipitation,"
                    "weather_code,wind_speed_10m"
                ),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "timezone": "auto",
                "forecast_days": 3,
            },
        )
        forecast.raise_for_status()
        data = forecast.json()

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    place_name = ", ".join(
        value for value in (place.get("name"), place.get("country")) if value
    )
    snippet = (
        f"Météo actuelle à {place_name}: "
        f"{current.get('temperature_2m')} °C, ressenti "
        f"{current.get('apparent_temperature')} °C, vent "
        f"{current.get('wind_speed_10m')} km/h, précipitations "
        f"{current.get('precipitation')} mm. "
        f"Prévisions maximales: {daily.get('temperature_2m_max', [])}; "
        f"minimales: {daily.get('temperature_2m_min', [])}; "
        f"probabilité maximale de pluie: "
        f"{daily.get('precipitation_probability_max', [])}."
    )
    url = (
        "https://open-meteo.com/en/docs"
        f"?latitude={place['latitude']}&longitude={place['longitude']}"
    )
    return {
        "status": "ok",
        "type": "weather",
        "results": [{
            "title": f"Météo pour {place_name}",
            "snippet": snippet,
            "url": url,
            "engine": "Open-Meteo",
            "quality": "trusted",
            "evidence_kind": "structured_api",
            "verified": True,
        }],
    }


def _crypto_result(symbol: str, timeout: int) -> Dict[str, Any]:
    pair = f"{quote(symbol)}-USD"
    url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
    with httpx.Client(timeout=timeout, trust_env=False) as http:
        response = http.get(url)
        response.raise_for_status()
        data = (response.json().get("data") or {})
    amount = data.get("amount")
    currency = data.get("currency", "USD")
    return {
        "status": "ok" if amount else "unavailable",
        "type": "crypto",
        "results": [{
            "title": f"Cours {symbol}/{currency}",
            "snippet": (
                f"Prix spot {symbol}: {amount} {currency}, "
                f"consulté le {datetime.date.today().isoformat()}."
            ),
            "url": url,
            "engine": "Coinbase",
            "quality": "trusted",
            "evidence_kind": "structured_api",
            "verified": True,
        }] if amount else [],
    }


def _stock_result(symbol: str, timeout: int) -> Dict[str, Any]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol)}?range=5d&interval=1d"
    )
    with httpx.Client(
        timeout=timeout,
        trust_env=False,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as http:
        response = http.get(url)
        response.raise_for_status()
        result = (((response.json().get("chart") or {}).get("result")) or [None])[0]
    if not result:
        return {"status": "unavailable", "type": "stock", "results": []}
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    currency = meta.get("currency") or ""
    exchange = meta.get("exchangeName") or ""
    return {
        "status": "ok" if price is not None else "unavailable",
        "type": "stock",
        "results": [{
            "title": f"Cours de {symbol}",
            "snippet": (
                f"Dernier cours de {symbol}: {price} {currency}. "
                f"Place de cotation: {exchange}. "
                f"Données consultées le {datetime.date.today().isoformat()}."
            ),
            "url": f"https://finance.yahoo.com/quote/{quote(symbol)}",
            "engine": "Yahoo Finance",
            "quality": "trusted",
            "evidence_kind": "structured_api",
            "verified": True,
        }] if price is not None else [],
    }


def run_specialized_tool(query: str, timeout: int = 5) -> Dict[str, Any]:
    request = detect_specialized_request(query)
    if not request:
        return {"status": "not_applicable", "type": None, "results": []}
    try:
        if request["type"] == "weather":
            return _weather_result(request["location"], timeout)
        if request["type"] == "crypto":
            return _crypto_result(request["symbol"], timeout)
        if request["type"] == "stock":
            return _stock_result(request["symbol"], timeout)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "type": request["type"],
            "results": [],
        }
    return {"status": "not_applicable", "type": None, "results": []}
