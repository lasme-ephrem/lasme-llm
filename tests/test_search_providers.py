import unittest
from unittest.mock import MagicMock, patch

from core.tools.search_providers import (
    SearchProviderError,
    detect_search_vertical,
    search_brave,
    search_openalex,
    search_wikipedia,
)


class SearchProviderAdapterTests(unittest.TestCase):
    def test_vertical_detection_is_conservative(self):
        self.assertEqual(
            detect_search_vertical("Trouve des études scientifiques sur les LLM"),
            "academic",
        )
        self.assertEqual(
            detect_search_vertical("Quelles sont les dernières actualités IA ?"),
            "news",
        )
        self.assertEqual(
            detect_search_vertical("Quelle est la date de naissance de Marie Curie ?"),
            "knowledge",
        )
        self.assertIsNone(
            detect_search_vertical("Écris-moi une fonction Python récursive")
        )

    def test_brave_normalizes_results_and_exposes_quota_headers(self):
        response = MagicMock(status_code=200)
        response.headers = {
            "X-RateLimit-Limit": "1000",
            "X-RateLimit-Remaining": "999",
        }
        response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Source officielle",
                        "url": "https://example.org/result",
                        "description": "Réponse actuelle.",
                        "extra_snippets": ["Détail complémentaire."],
                    }
                ]
            }
        }
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response

        with patch(
            "core.tools.search_providers.httpx.Client",
            return_value=client,
        ):
            report = search_brave("question", "secret-key", 5)

        request = client.__enter__.return_value.get.call_args
        self.assertEqual(
            request.kwargs["headers"]["X-Subscription-Token"],
            "secret-key",
        )
        self.assertEqual(report["results"][0]["engine"], "Brave Search")
        self.assertIn("Détail complémentaire", report["results"][0]["snippet"])
        self.assertEqual(report["quota"]["remaining"], "999")

    def test_brave_classifies_quota_without_leaking_response(self):
        response = MagicMock(status_code=429)
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response

        with (
            patch(
                "core.tools.search_providers.httpx.Client",
                return_value=client,
            ),
            self.assertRaises(SearchProviderError) as raised,
        ):
            search_brave("question", "secret-key", 5)

        self.assertEqual(raised.exception.reason, "quota_or_rate_limit")
        self.assertNotIn("secret-key", str(raised.exception))

    def test_openalex_reconstructs_abstract_and_ignores_retractions(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "results": [
                {
                    "display_name": "Reliable paper",
                    "doi": "https://doi.org/10.1000/example",
                    "publication_date": "2026-01-02",
                    "is_retracted": False,
                    "abstract_inverted_index": {
                        "A": [0],
                        "useful": [1],
                        "abstract": [2],
                    },
                    "authorships": [
                        {"author": {"display_name": "Ada Lovelace"}}
                    ],
                    "primary_location": {
                        "source": {"display_name": "Example Journal"}
                    },
                    "cited_by_count": 12,
                },
                {
                    "display_name": "Retracted paper",
                    "id": "https://openalex.org/W2",
                    "is_retracted": True,
                },
            ]
        }
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with patch(
            "core.tools.search_providers.httpx.Client",
            return_value=client,
        ):
            results = search_openalex("research", "openalex-key", 5)

        self.assertEqual(len(results), 1)
        self.assertIn("A useful abstract", results[0]["snippet"])
        self.assertIn("Ada Lovelace", results[0]["snippet"])

    def test_wikipedia_returns_intro_and_canonical_url(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "query": {
                "pages": [
                    {
                        "index": 1,
                        "title": "Marie Curie",
                        "extract": "Marie Curie est une physicienne et chimiste.",
                        "fullurl": "https://fr.wikipedia.org/wiki/Marie_Curie",
                    }
                ]
            }
        }
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with patch(
            "core.tools.search_providers.httpx.Client",
            return_value=client,
        ):
            results = search_wikipedia("Marie Curie", 5)

        self.assertEqual(results[0]["engine"], "Wikimedia")
        self.assertIn("physicienne", results[0]["snippet"])


if __name__ == "__main__":
    unittest.main()
