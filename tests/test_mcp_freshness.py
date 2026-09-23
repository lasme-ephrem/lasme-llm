"""Formateurs de fraîcheur : payloads fictifs, aucun réseau."""

import unittest

from core.mcp.servers.freshness import (
    format_hn,
    format_sports,
    format_weather,
    format_wiki,
)


def _as_hits(value):
    if isinstance(value, dict) and (
        "engine" in value or "url" in value or "snippet" in value
    ):
        return [value]
    if isinstance(value, dict):
        for key in ("results", "hits", "items"):
            nested = value.get(key)
            if isinstance(nested, (list, tuple)):
                return list(nested)
    if isinstance(value, (list, tuple)):
        return list(value)
    raise AssertionError(f"forme inattendue: {type(value)!r}")


def _field(hit, name: str) -> str:
    if isinstance(hit, dict):
        return str(hit.get(name) or "")
    return str(getattr(hit, name, "") or "")


_FRENCH_WEATHER = (
    "météo",
    "température",
    "degré",
    "pluie",
    "vent",
    "prévision",
    "ressenti",
    "précipitation",
    "humidité",
    "nuage",
)


class FreshnessFormatterTests(unittest.TestCase):
    def test_format_weather_is_french(self):
        hits = _as_hits(
            format_weather(
                {
                    "results": [
                        {
                            "name": "Lyon",
                            "country": "France",
                            "latitude": 45.75,
                            "longitude": 4.85,
                        }
                    ]
                },
                {
                    "current": {
                        "temperature_2m": 18,
                        "wind_speed_10m": 12,
                        "weather_code": 1,
                    },
                    "daily": {
                        "time": ["2026-09-23"],
                        "temperature_2m_max": [22],
                        "temperature_2m_min": [12],
                    },
                },
            )
        )
        self.assertIn("weather", [_field(hit, "engine") for hit in hits])
        snippets = " ".join(_field(hit, "snippet") for hit in hits).casefold()
        self.assertTrue(snippets.strip())
        self.assertTrue(
            any(marker in snippets for marker in _FRENCH_WEATHER),
            snippets,
        )

    def test_format_hn_has_engine_and_url(self):
        hits = _as_hits(
            format_hn(
                {
                    "hits": [
                        {
                            "title": "Speculative decoding",
                            "url": "https://exemple.fr/speculative",
                            "points": 120,
                            "objectID": "42",
                        }
                    ]
                }
            )
        )
        self.assertTrue(any(_field(hit, "engine") == "hackernews" for hit in hits))
        self.assertTrue(any(_field(hit, "url").startswith("http") for hit in hits))

    def test_format_wiki_engine(self):
        hits = _as_hits(
            format_wiki(
                {"query": {"search": [{"title": "Ada Lovelace"}]}},
                {
                    "title": "Ada Lovelace",
                    "extract": "Mathématicienne britannique.",
                    "content_urls": {
                        "desktop": {
                            "page": "https://fr.wikipedia.org/wiki/Ada_Lovelace"
                        }
                    },
                },
            )
        )
        self.assertTrue(any(_field(hit, "engine") == "wikipedia" for hit in hits))

    def test_format_sports_engine(self):
        hits = _as_hits(
            format_sports(
                {
                    "events": [
                        {
                            "idEvent": "1",
                            "strEvent": "Finale",
                            "strHomeTeam": "France",
                            "strAwayTeam": "Bresil",
                            "intHomeScore": 2,
                            "intAwayScore": 1,
                            "dateEvent": "2026-07-19",
                            "strLeague": "Coupe du monde",
                        }
                    ]
                },
                {"teams": []},
            )
        )
        self.assertTrue(any(_field(hit, "engine") == "sports" for hit in hits))


if __name__ == "__main__":
    unittest.main()
