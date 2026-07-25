import unittest
from unittest.mock import Mock, patch

import core.tools.web_search as web_search


def _official_world_cup_result(engine: str):
    return {
        "title": "Spain crowned FIFA World Cup 2026 champions",
        "snippet": (
            "Spain won the 2026 FIFA World Cup final and were crowned "
            "world champions."
        ),
        "url": "https://www.fifa.com/tournaments/world-cup/2026/final",
        "engine": engine,
        "engine_score": 0.95,
    }


class SequentialSearchProviderTests(unittest.TestCase):
    def test_sonar_success_stops_before_tavily_and_duckduckgo(self):
        tavily = Mock()
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(
                web_search,
                "_search_with_sonar",
                return_value={
                    "results": [_official_world_cup_result("Perplexity Sonar")],
                    "answer": "Spain won.",
                    "usage": {},
                },
            ) as sonar,
            patch.object(web_search, "tavily_client", tavily),
            patch.object(
                web_search,
                "DDGS",
                side_effect=AssertionError("DuckDuckGo should not run"),
            ),
        ):
            report = web_search.search_web_detailed(
                "Qui est le dernier vainqueur de la Coupe du monde ?"
            )

        sonar.assert_called_once()
        tavily.search.assert_not_called()
        self.assertEqual(report["engine"], "Perplexity Sonar")
        self.assertEqual(
            report["strategy"]["provider_attempts"][0]["status"],
            "ok",
        )

    def test_sonar_quota_falls_back_to_tavily(self):
        tavily = Mock()
        tavily.search.return_value = {
            "results": [
                {
                    "title": "Spain crowned FIFA World Cup 2026 champions",
                    "content": (
                        "Spain won the 2026 FIFA World Cup final and became "
                        "world champions."
                    ),
                    "url": "https://www.fifa.com/tournaments/world-cup/2026/final",
                    "score": 0.95,
                }
            ]
        }
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(
                web_search,
                "_search_with_sonar",
                side_effect=web_search.SonarSearchError(
                    "quota_or_rate_limit",
                    429,
                ),
            ),
            patch.object(web_search, "tavily_client", tavily),
            patch.object(
                web_search,
                "DDGS",
                side_effect=AssertionError("DuckDuckGo should not run"),
            ),
        ):
            report = web_search.search_web_detailed(
                "Qui est le dernier vainqueur de la Coupe du monde ?"
            )

        tavily.search.assert_called_once()
        self.assertEqual(report["engine"], "Tavily AI")
        self.assertEqual(
            report["strategy"]["provider_attempts"][0]["reason"],
            "quota_or_rate_limit",
        )
        self.assertEqual(
            report["strategy"]["provider_attempts"][1]["status"],
            "ok",
        )

    def test_tavily_failure_falls_back_to_duckduckgo(self):
        tavily = Mock()
        tavily.search.side_effect = RuntimeError("Tavily unavailable")
        ddgs = Mock()
        ddgs.text.return_value = [
            {
                "title": "Spain crowned FIFA World Cup 2026 champions",
                "body": (
                    "Spain won the 2026 FIFA World Cup final and became "
                    "world champions."
                ),
                "href": "https://www.fifa.com/tournaments/world-cup/2026/final",
            }
        ]
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(
                web_search,
                "_search_with_sonar",
                side_effect=web_search.SonarSearchError(
                    "quota_or_rate_limit",
                    429,
                ),
            ),
            patch.object(web_search, "tavily_client", tavily),
            patch.object(web_search, "DDGS", return_value=ddgs),
        ):
            report = web_search.search_web_detailed(
                "Qui est le dernier vainqueur de la Coupe du monde ?"
            )

        self.assertGreaterEqual(tavily.search.call_count, 1)
        ddgs.text.assert_called_once()
        self.assertEqual(report["engine"], "DuckDuckGo")
        self.assertEqual(
            report["strategy"]["provider_attempts"][-1]["status"],
            "ok",
        )

    def test_sonar_http_statuses_are_classified_without_response_details(self):
        self.assertEqual(
            web_search._sonar_error_reason(429),
            "quota_or_rate_limit",
        )
        self.assertEqual(
            web_search._sonar_error_reason(401),
            "authentication_failed",
        )
        self.assertEqual(
            web_search._sonar_error_reason(503),
            "provider_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
