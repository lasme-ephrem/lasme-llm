import unittest
import json
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
    def test_comparison_ledger_keeps_only_claims_backed_by_returned_evidence(self):
        results = [
            {
                "title": "DeepSeek V3.2 pricing",
                "snippet": (
                    "DeepSeek V3.2 offers a 128K context window. Input costs "
                    "$0.28 and output costs $0.42 per million tokens."
                ),
                "url": "https://api-docs.deepseek.com/quick_start/pricing",
            },
            {
                "title": "GPT-5.4 pricing",
                "snippet": (
                    "GPT-5.4 has a 1M context window. Input costs $2.50 and "
                    "output costs $15 per million tokens."
                ),
                "url": "https://openai.com/api/pricing/",
            },
        ]
        raw = json.dumps(
            {
                "title": "Comparatif actuel",
                "scope": "Modèles généralistes via API",
                "as_of": "2026-07-30",
                "summary": "Deux offres documentées.",
                "rows": [
                    {
                        "provider": "DeepSeek",
                        "model": "DeepSeek V3.2",
                        "positioning": "Généraliste",
                        "access": "API",
                        "context_window": "128K",
                        "input_price": "$0.28 / 1M tokens",
                        "output_price": "$0.42 / 1M tokens",
                        "strengths": ["Contexte 128K"],
                        "limitations": ["Limite inventée de 999 appels"],
                        "benchmarks": [],
                        "evidence_urls": [
                            "https://api-docs.deepseek.com/quick_start/pricing"
                        ],
                        "model_source_url": (
                            "https://api-docs.deepseek.com/quick_start/pricing"
                        ),
                        "context_source_url": (
                            "https://api-docs.deepseek.com/quick_start/pricing"
                        ),
                        "pricing_source_url": (
                            "https://api-docs.deepseek.com/quick_start/pricing"
                        ),
                    },
                    {
                        "provider": "OpenAI",
                        "model": "GPT-5.4",
                        "positioning": "Généraliste avancé",
                        "access": "API",
                        "context_window": "1M",
                        "input_price": "$2.50 / 1M tokens",
                        "output_price": "$15 / 1M tokens",
                        "strengths": [],
                        "limitations": [],
                        "benchmarks": [],
                        "evidence_urls": ["https://openai.com/api/pricing/"],
                        "model_source_url": "https://openai.com/api/pricing/",
                        "context_source_url": "https://openai.com/api/pricing/",
                        "pricing_source_url": "https://openai.com/api/pricing/",
                    },
                    {
                        "provider": "Imaginaire",
                        "model": "Ghost 9",
                        "positioning": "Inconnu",
                        "access": "API",
                        "context_window": "9M",
                        "input_price": "$0",
                        "output_price": "$0",
                        "strengths": [],
                        "limitations": [],
                        "benchmarks": [],
                        "evidence_urls": ["https://invalid.example/pricing"],
                        "model_source_url": "https://invalid.example/pricing",
                        "context_source_url": "https://invalid.example/pricing",
                        "pricing_source_url": "https://invalid.example/pricing",
                    },
                ],
                "takeaways": ["Comparer le périmètre avant le prix."],
                "caveats": ["Les tarifs changent."],
            }
        )

        ledger, selected = web_search._validated_comparison_ledger(
            raw,
            results,
        )
        self.assertIsNotNone(ledger)
        self.assertEqual(len(ledger["rows"]), 2)
        self.assertEqual(ledger["rows"][0]["limitations"], [])
        self.assertEqual(len(selected), 2)
        rendered = web_search._render_comparison_ledger(ledger)
        self.assertIn("DeepSeek V3.2", rendered)
        self.assertIn("GPT-5.4", rendered)
        self.assertNotIn("Ghost 9", rendered)
        self.assertNotIn("[Source", rendered)

    def test_sonar_product_comparison_requests_structured_output(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "Comparatif",
                                "scope": "API",
                                "as_of": "2026-07-30",
                                "summary": "Synthèse.",
                                "rows": [
                                    {
                                        "provider": "DeepSeek",
                                        "model": "DeepSeek V3.2",
                                        "positioning": "Généraliste",
                                        "access": "API",
                                        "context_window": "128K",
                                        "input_price": "$0.28",
                                        "output_price": "$0.42",
                                        "strengths": [],
                                        "limitations": [],
                                        "benchmarks": [],
                                        "evidence_urls": [
                                            "https://api-docs.deepseek.com/pricing"
                                        ],
                                        "model_source_url": (
                                            "https://api-docs.deepseek.com/pricing"
                                        ),
                                        "context_source_url": (
                                            "https://api-docs.deepseek.com/pricing"
                                        ),
                                        "pricing_source_url": (
                                            "https://api-docs.deepseek.com/pricing"
                                        ),
                                    },
                                    {
                                        "provider": "OpenAI",
                                        "model": "GPT-5.4",
                                        "positioning": "Généraliste",
                                        "access": "API",
                                        "context_window": "1M",
                                        "input_price": "$2.50",
                                        "output_price": "$15",
                                        "strengths": [],
                                        "limitations": [],
                                        "benchmarks": [],
                                        "evidence_urls": [
                                            "https://openai.com/api/pricing/"
                                        ],
                                        "model_source_url": (
                                            "https://openai.com/api/pricing/"
                                        ),
                                        "context_source_url": (
                                            "https://openai.com/api/pricing/"
                                        ),
                                        "pricing_source_url": (
                                            "https://openai.com/api/pricing/"
                                        ),
                                    },
                                ],
                                "takeaways": [],
                                "caveats": [],
                            }
                        )
                    }
                }
            ],
            "citations": [
                "https://api-docs.deepseek.com/pricing",
                "https://openai.com/api/pricing/",
            ],
            "search_results": [
                {
                    "title": "DeepSeek V3.2 pricing",
                    "url": "https://api-docs.deepseek.com/pricing",
                    "snippet": "DeepSeek V3.2 128K $0.28 input $0.42 output.",
                },
                {
                    "title": "GPT-5.4 pricing",
                    "url": "https://openai.com/api/pricing/",
                    "snippet": "GPT-5.4 1M $2.50 input $15 output.",
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
                "Compare les modèles LLM DeepSeek et OpenAI",
                [],
                8,
            )

        payload = http.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertIsNotNone(report["comparison_ledger"])
        self.assertNotIn("[Source", report["provider_answer"])

    def test_generic_news_hubs_are_not_evidence(self):
        self.assertTrue(
            web_search._is_generic_news_listing(
                {
                    "title": (
                        "Intelligence artificielle - Actualités, vidéos "
                        "et infos en direct"
                    ),
                    "url": "https://www.lemonde.fr/intelligence-artificielle/",
                }
            )
        )
        self.assertTrue(
            web_search._is_generic_news_listing(
                {
                    "title": "Intelligence artificielle",
                    "url": (
                        "https://www.numerama.com/tech/"
                        "intelligence-artificielle/"
                    ),
                }
            )
        )
        self.assertFalse(
            web_search._is_generic_news_listing(
                {
                    "title": "Moonshot publie les poids ouverts de Kimi K3",
                    "url": "https://example.com/actualites/kimi-k3-open-weights",
                }
            )
        )
        self.assertTrue(
            web_search._is_generic_news_listing(
                {
                    "title": "Les 10 meilleures newsletters IA à suivre",
                    "url": "https://example.com/newsletters-ia",
                }
            )
        )

    def test_ai_news_uses_a_concise_gdelt_query(self):
        query = web_search._news_specialist_query(
            "Quelles sont les dernières nouvelles dans le monde de l'IA ?"
        )
        self.assertIn("artificial intelligence", query)
        self.assertNotIn("Quelles", query)
        web_query = web_search._news_web_query(
            "Quelles sont les dernières nouvelles dans le monde de l'IA ?"
        )
        self.assertIn("actualités intelligence artificielle", web_query)
        self.assertRegex(web_query, r"\d{4}-\d{2}$")

    def test_provider_passthrough_requires_primary_evidence_for_news(self):
        generic_results = [
            {
                "title": "Rumeur IA",
                "url": "https://example.net/ai-rumor",
                "snippet": "Une annonce non confirmée.",
            },
            {
                "title": "Reprise de la rumeur",
                "url": "https://example.org/ai-rumor",
                "snippet": "La même annonce non confirmée.",
            },
        ]
        self.assertFalse(
            web_search._provider_answer_is_high_confidence(
                "Quelles sont les dernières nouvelles dans l'IA ?",
                generic_results,
                [],
            )
        )
        self.assertTrue(
            web_search._provider_answer_is_high_confidence(
                "Où trouver les poids de Kimi K3 ?",
                [
                    {
                        "title": "Kimi K3",
                        "url": "https://huggingface.co/moonshotai/Kimi-K3",
                        "snippet": "Dépôt officiel.",
                    }
                ],
                ["moonshot.ai", "huggingface.co", "arxiv.org"],
            )
        )

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
            patch.object(web_search.settings, "brave_search_api_key", ""),
            patch.object(web_search.settings, "search_specialists_enabled", False),
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
            patch.object(web_search.settings, "brave_search_api_key", ""),
            patch.object(web_search.settings, "search_specialists_enabled", False),
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
            next(
                item
                for item in report["strategy"]["provider_attempts"]
                if item["provider"] == "Tavily AI"
            )["status"],
            "ok",
        )

    def test_sonar_quota_falls_back_to_searxng_before_tavily(self):
        tavily = Mock()
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(web_search.settings, "brave_search_api_key", ""),
            patch.object(web_search.settings, "search_specialists_enabled", False),
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
            next(
                item
                for item in report["strategy"]["provider_attempts"]
                if item["provider"] == "SearXNG"
            )["status"],
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
            patch.object(web_search.settings, "brave_search_api_key", ""),
            patch.object(web_search.settings, "search_specialists_enabled", False),
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

    def test_sonar_quota_falls_back_to_brave_before_tavily(self):
        tavily = Mock()
        brave_result = _official_world_cup_result("Brave Search")
        with (
            patch.object(web_search.settings, "perplexity_api_key", "test-key"),
            patch.object(web_search.settings, "brave_search_api_key", "brave-key"),
            patch.object(web_search.settings, "search_specialists_enabled", False),
            patch.object(web_search.settings, "searxng_enabled", False),
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
                "search_brave",
                return_value={
                    "results": [brave_result],
                    "quota": {"remaining": "999"},
                },
            ) as brave,
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

        brave.assert_called_once()
        tavily.search.assert_not_called()
        self.assertEqual(report["engine"], "Brave Search")
        attempt = next(
            item
            for item in report["strategy"]["provider_attempts"]
            if item["provider"] == "Brave Search"
        )
        self.assertEqual(attempt["status"], "ok")
        self.assertEqual(attempt["quota"]["remaining"], "999")

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
