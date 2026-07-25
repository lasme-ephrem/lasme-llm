import unittest
from unittest.mock import MagicMock, Mock, patch

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
    def test_sonar_preserves_citation_order_and_conversation_context(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {"message": {"content": "Réponse actuelle [1] puis [2]."}}
            ],
            "citations": [
                "https://www.uefa.com/article",
                "https://www.fifa.com/article",
            ],
            "search_results": [
                {
                    "title": "Première source",
                    "url": "https://www.fifa.com/article",
                    "snippet": "Premier extrait.",
                },
                {
                    "title": "Deuxième source",
                    "url": "https://www.uefa.com/article",
                    "snippet": "Deuxième extrait.",
                },
            ],
        }
        http = MagicMock()
        http.__enter__.return_value.post.return_value = response

        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(web_search.httpx, "Client", return_value=http),
        ):
            report = web_search._search_with_sonar(
                "Et le meilleur buteur ?",
                [],
                8,
                conversation_messages=[
                    {
                        "role": "user",
                        "content": "Qui a gagné la Coupe du monde ?",
                    },
                    {
                        "role": "assistant",
                        "content": "Ancienne réponse potentiellement fausse.",
                    },
                ],
            )

        payload = http.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertTrue(
            any(
                "Coupe du monde" in message["content"]
                for message in payload["messages"]
            )
        )
        self.assertEqual(report["answer_mode"], "provider")
        self.assertEqual(
            [item["url"] for item in report["results"]],
            [
                "https://www.uefa.com/article",
                "https://www.fifa.com/article",
            ],
        )
        self.assertEqual(
            [item["citation_index"] for item in report["results"]],
            [1, 2],
        )

    def test_sonar_success_stops_before_tavily_and_duckduckgo(self):
        tavily = Mock()
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(
                web_search,
                "_search_with_sonar",
                return_value={
                    "results": [_official_world_cup_result("Perplexity Sonar")],
                    "provider_answer": "L'Espagne a gagné [1].",
                    "provider_citations": [
                        "https://www.fifa.com/tournaments/world-cup/2026/final"
                    ],
                    "answer_mode": "provider",
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
        self.assertEqual(report["answer_mode"], "provider")
        self.assertEqual(report["provider_answer"], "L'Espagne a gagné [1].")
        self.assertEqual(
            report["strategy"]["stop_reason"],
            "provider_answer",
        )
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
            patch.object(web_search.settings, "searxng_enabled", False),
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
            report["strategy"]["provider_attempts"][2]["status"],
            "ok",
        )

    def test_sonar_quota_falls_back_to_searxng_before_tavily(self):
        tavily = Mock()
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(web_search.settings, "searxng_enabled", True),
            patch.object(
                web_search,
                "_search_with_sonar",
                side_effect=web_search.SonarSearchError(
                    "quota_or_rate_limit",
                    429,
                ),
            ),
            patch.object(
                web_search,
                "_search_with_searxng",
                return_value=[_official_world_cup_result("SearXNG")],
            ) as searxng,
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

        searxng.assert_called_once()
        tavily.search.assert_not_called()
        self.assertEqual(report["engine"], "SearXNG")
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
            patch.object(web_search.settings, "searxng_enabled", False),
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
