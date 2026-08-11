import unittest

from core.tools.search_ranking import (
    adaptive_select_results,
    build_search_plan,
    canonical_url,
    is_product_comparison,
    rank_candidates,
)


class AdaptiveSearchRankingTests(unittest.TestCase):
    def test_mutable_llm_comparison_uses_structured_grounding(self):
        self.assertTrue(
            is_product_comparison(
                "Compare DeepSeek, Kimi, les modèles d'OpenAI, Google "
                "et Anthropic"
            )
        )

    def test_direct_official_answer_can_stop_after_one_source(self):
        candidates = [
            {
                "title": "FIFA World Cup 2026 official winner",
                "snippet": (
                    "L'Espagne a remporté la finale 2026 et a été sacrée "
                    "championne de la Coupe du monde."
                ),
                "url": "https://www.fifa.com/tournaments/world-cup/2026/final",
                "engine": "Tavily AI",
                "engine_score": 0.94,
            },
            {
                "title": "World Cup recap",
                "snippet": "A recap of the 2026 World Cup final.",
                "url": "https://example.com/world-cup-recap",
                "engine": "DuckDuckGo",
            },
        ]

        report = adaptive_select_results(
            candidates,
            "dernier vainqueur de la Coupe du monde 2026",
            official_domains=["fifa.com"],
        )

        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["quality"], "official")
        self.assertTrue(report["strategy"]["sufficient"])
        self.assertEqual(
            report["strategy"]["stop_reason"],
            "authoritative_source_found",
        )

    def test_historical_winners_list_does_not_answer_latest_winner(self):
        candidates = [
            {
                "title": "Les vainqueurs de la Coupe du Monde : 1982-2026",
                "snippet": (
                    "Les vainqueurs de la Coupe du Monde : 1982-2026 ; "
                    "Vainqueur : Italie. Finaliste : Allemagne."
                ),
                "url": "https://fifa.com/world-cup/winners-1982-2026",
                "engine": "Tavily AI",
                "engine_score": 0.95,
            }
        ]

        report = adaptive_select_results(
            candidates,
            "Qui est le dernier vainqueur de la Coupe du monde ?",
            official_domains=["fifa.com"],
        )

        self.assertFalse(report["strategy"]["sufficient"])
        self.assertLess(report["strategy"]["answerability"], 0.58)

    def test_answerable_winner_source_excludes_topical_archive(self):
        candidates = [
            {
                "title": "Les vainqueurs de la Coupe du Monde : 1982-2026",
                "snippet": "Vainqueur : Italie. Finaliste : Allemagne.",
                "url": "https://fifa.com/world-cup/winners-1982-2026",
                "engine": "Tavily AI",
                "engine_score": 0.99,
            },
            {
                "title": "Spain crowned FIFA World Cup 2026 champions",
                "snippet": (
                    "Spain claimed the 2026 World Cup crown with victory over "
                    "Argentina in the final."
                ),
                "url": "https://fifa.com/news/spain-world-cup-2026-champions",
                "engine": "Tavily AI",
                "engine_score": 0.7,
            },
        ]

        report = adaptive_select_results(
            candidates,
            "Qui est le dernier vainqueur de la Coupe du monde ?",
            official_domains=["fifa.com"],
        )

        self.assertEqual(len(report["results"]), 1)
        self.assertIn("Spain", report["results"][0]["title"])
        self.assertTrue(report["strategy"]["sufficient"])

    def test_official_community_forum_is_not_sufficient_by_itself(self):
        candidates = [
            {
                "title": "Python latest stable version discussion",
                "snippet": "Community discussion about the latest Python version.",
                "url": "https://discuss.python.org/t/latest-version/123",
                "engine": "Tavily AI",
                "engine_score": 0.96,
            }
        ]

        report = adaptive_select_results(
            candidates,
            "latest stable Python version",
            official_domains=["python.org"],
        )

        self.assertFalse(report["strategy"]["sufficient"])
        self.assertEqual(report["results"][0]["quality"], "standard")

    def test_standard_question_uses_independent_sources(self):
        candidates = [
            {
                "title": "Python 3.14 latest stable version",
                "snippet": "Python 3.14 is the latest stable version available.",
                "url": "https://python.org/downloads/",
                "engine": "Tavily AI",
                "engine_score": 0.9,
            },
            {
                "title": "Python 3.14 release notes",
                "snippet": "The latest Python version and its release date.",
                "url": "https://docs.python.org/3.14/whatsnew/",
                "engine": "DuckDuckGo",
            },
            {
                "title": "Python version overview",
                "snippet": "An overview of currently available Python releases.",
                "url": "https://example.net/python-versions",
                "engine": "DuckDuckGo",
            },
        ]

        report = adaptive_select_results(
            candidates,
            "quelle est la dernière version Python disponible",
        )

        self.assertGreaterEqual(len(report["results"]), 2)
        selected_domains = {
            result["url"].split("/")[2] for result in report["results"]
        }
        self.assertGreaterEqual(len(selected_domains), 2)

    def test_temporal_question_requires_an_authoritative_source(self):
        candidates = [
            {
                "title": "Latest stable Python version available",
                "snippet": "The latest stable Python version available today.",
                "url": "https://hosting-blog.example/python-version",
                "engine": "Tavily AI",
                "engine_score": 0.9,
            },
            {
                "title": "What is the latest Python version?",
                "snippet": "Community answers about the latest available version.",
                "url": "https://forum.example/python-version",
                "engine": "DuckDuckGo",
            },
        ]

        report = adaptive_select_results(
            candidates,
            "latest stable Python version available",
        )

        self.assertFalse(report["strategy"]["sufficient"])
        self.assertEqual(
            report["strategy"]["stop_reason"],
            "insufficient_evidence",
        )

    def test_complex_question_gets_a_larger_evidence_set(self):
        candidates = [
            {
                "title": f"Analyse des impacts économiques climatiques {index}",
                "snippet": (
                    "Analyse comparée des impacts économiques et climatiques, "
                    "avec limites, données et perspectives."
                ),
                "url": f"https://source{index}.org/report",
                "engine": "Tavily AI",
                "engine_score": 0.8 - index * 0.02,
            }
            for index in range(1, 6)
        ]

        report = adaptive_select_results(
            candidates,
            "Compare les impacts économiques et climatiques, leurs limites et perspectives",
        )

        self.assertEqual(build_search_plan(
            "Compare les impacts économiques et climatiques, leurs limites et perspectives"
        )["scope"], "complex")
        self.assertGreaterEqual(len(report["results"]), 3)
        self.assertLessEqual(len(report["results"]), 6)

    def test_duplicates_and_tracking_parameters_are_removed(self):
        candidates = [
            {
                "title": "Official release",
                "snippet": "Latest official product release information.",
                "url": "https://example.com/release?utm_source=newsletter",
                "engine": "Tavily AI",
                "engine_score": 0.8,
            },
            {
                "title": "Official release duplicate",
                "snippet": "Latest official product release information.",
                "url": "https://www.example.com/release",
                "engine": "DuckDuckGo",
            },
        ]

        ranked = rank_candidates(candidates, "latest product release")

        self.assertEqual(len(ranked), 1)
        self.assertEqual(
            canonical_url(candidates[0]["url"]),
            canonical_url(candidates[1]["url"]),
        )

    def test_subdomains_do_not_count_as_independent_sources(self):
        candidates = [
            {
                "title": "Python release",
                "snippet": "Latest stable Python release and version.",
                "url": "https://python.org/downloads/",
                "engine": "Tavily AI",
                "engine_score": 0.9,
            },
            {
                "title": "Python release documentation",
                "snippet": "Documentation for the latest Python release.",
                "url": "https://docs.python.org/3/whatsnew/",
                "engine": "DuckDuckGo",
            },
        ]

        report = adaptive_select_results(
            candidates,
            "latest stable Python release version",
        )

        self.assertEqual(report["strategy"]["independent_domains"], 1)

    def test_low_signal_social_result_is_penalized(self):
        candidates = [
            {
                "title": "World Cup result video",
                "snippet": "Latest World Cup winner result.",
                "url": "https://youtube.com/watch?v=123",
                "engine": "DuckDuckGo",
            },
            {
                "title": "World Cup official result",
                "snippet": "Latest World Cup winner and official final result.",
                "url": "https://fifa.com/tournaments/world-cup/final",
                "engine": "Tavily AI",
                "engine_score": 0.8,
            },
        ]

        ranked = rank_candidates(
            candidates,
            "latest World Cup winner",
            official_domains=["fifa.com"],
            low_signal_domains=["youtube.com"],
        )

        self.assertEqual(ranked[0]["hostname"], "fifa.com")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_first_low_relevance_candidate_is_not_accepted(self):
        report = adaptive_select_results(
            [
                {
                    "title": "Recette de cuisine",
                    "snippet": "Préparer une tarte aux pommes.",
                    "url": "https://example.com/tarte",
                    "engine": "DuckDuckGo",
                }
            ],
            "bilan actuel de Lionel Messi en Coupe du monde 2026",
        )

        self.assertEqual(report["results"], [])
        self.assertEqual(
            report["strategy"]["stop_reason"],
            "no_relevant_source",
        )


if __name__ == "__main__":
    unittest.main()
