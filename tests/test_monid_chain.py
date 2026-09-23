"""Monid as first link provider of ``search_web_detailed``.

Chain-level tests only: every provider is mocked (Monid, Brave, Tavily,
DuckDuckGo, Sonar) so the suite never touches the network and never
needs a real key. What is exercised is the orchestration: Monid tried
first, automatic fallback to the local chain when it returns nothing or
fails, and no attempt at all when ``MONID_API_KEY`` is absent.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

import core.tools.web_search as web_search


def _official_world_cup_result(engine: str, url: str | None = None):
    return {
        "title": "Spain crowned FIFA World Cup 2026 champions",
        "snippet": (
            "Spain won the 2026 FIFA World Cup final and were crowned "
            "world champions."
        ),
        "url": url
        or "https://www.fifa.com/tournaments/world-cup/2026/final",
        "engine": engine,
        "engine_score": 0.95,
    }


def _monid_links(count: int = 3):
    """Raw {title, url, snippet} links as returned by monid_provider."""
    links = [
        {
            "title": "Spain crowned FIFA World Cup 2026 champions",
            "url": "https://www.fifa.com/tournaments/world-cup/2026/final",
            "snippet": (
                "Spain won the 2026 FIFA World Cup final and were "
                "crowned world champions."
            ),
        }
    ]
    for index in range(2, count + 1):
        links.append(
            {
                "title": f"World Cup 2026 coverage part {index}",
                "url": (
                    "https://www.fifa.com/tournaments/world-cup/2026/"
                    f"reporting-{index}"
                ),
                "snippet": (
                    "Spain won the 2026 FIFA World Cup final and became "
                    f"world champions. Report {index}."
                ),
            }
        )
    return links


class MonidChainTests(unittest.TestCase):
    """search_web_detailed with Monid inserted as provider n°1."""

    def _run_chain(self, *, monid_available, monid_links, monid_side_effect=None):
        monid_search = AsyncMock(
            return_value=monid_links,
            side_effect=monid_side_effect,
        )
        brave_result = _official_world_cup_result("Brave Search")
        tavily = Mock()
        with (
            patch.object(web_search.settings, "perplexity_api_key", ""),
            patch.object(
                web_search.settings, "search_specialists_enabled", False
            ),
            patch.object(web_search.settings, "searxng_enabled", False),
            patch.object(
                web_search.settings, "brave_search_api_key", "brave-key"
            ),
            patch.object(
                web_search.monid_provider,
                "is_available",
                return_value=monid_available,
            ),
            patch.object(
                web_search.monid_provider,
                "search_links_cross",
                monid_search,
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
        return report, monid_search, brave, tavily

    def test_monid_results_feed_the_chain_and_stop_before_brave(self):
        """Monid answers with 3 links: they are ranked into the final
        results, ``engines_used`` reports monid, and once the adaptive
        report judges the evidence sufficient the chain short-circuits
        (Brave and the providers below are never called)."""
        report, monid_search, brave, tavily = self._run_chain(
            monid_available=True,
            monid_links=_monid_links(3),
        )

        monid_search.assert_called_once()
        brave.assert_not_called()
        tavily.search.assert_not_called()

        engines = report["engine"] or ""
        self.assertIn("monid", engines)
        self.assertNotIn("Brave Search", engines)
        result_urls = [item["url"] for item in report["results"]]
        self.assertIn(
            "https://www.fifa.com/tournaments/world-cup/2026/final",
            result_urls,
        )
        attempts = {
            item["provider"]: item["status"]
            for item in report["strategy"]["provider_attempts"]
        }
        self.assertEqual(attempts.get("monid"), "ok")
        self.assertEqual(
            attempts.get("Perplexity Sonar"),
            "not_configured",
        )
        self.assertEqual(
            attempts.get("Brave Search"),
            "skipped_sufficient",
        )
        self.assertTrue(report["strategy"]["sufficient"])

    def test_monid_empty_results_fall_through_to_brave(self):
        """Monid returns []: the local chain takes over and Brave's
        results land in the final payload."""
        report, monid_search, brave, _ = self._run_chain(
            monid_available=True,
            monid_links=[],
        )

        monid_search.assert_called_once()
        brave.assert_called_once()
        self.assertNotIn("monid", report["engine"] or "")
        self.assertIn("Brave Search", report["engine"])
        result_urls = [item["url"] for item in report["results"]]
        self.assertIn(
            "https://www.fifa.com/tournaments/world-cup/2026/final",
            result_urls,
        )
        attempts = {
            item["provider"]: item["status"]
            for item in report["strategy"]["provider_attempts"]
        }
        self.assertEqual(attempts.get("monid"), "empty")
        self.assertEqual(attempts.get("Brave Search"), "ok")

    def test_monid_failure_never_breaks_the_chain(self):
        """Monid raising must be absorbed: warning, then Brave serves
        the query and the report stays usable."""
        report, monid_search, brave, _ = self._run_chain(
            monid_available=True,
            monid_links=[],
            monid_side_effect=RuntimeError("monid gateway down"),
        )

        monid_search.assert_called_once()
        brave.assert_called_once()
        self.assertTrue(report["results"])
        self.assertIn("Brave Search", report["engine"])
        self.assertTrue(
            any(error.startswith("monid:") for error in report["errors"]),
            report["errors"],
        )
        attempts = {
            item["provider"]: item["status"]
            for item in report["strategy"]["provider_attempts"]
        }
        self.assertEqual(attempts.get("monid"), "fallback")
        self.assertEqual(attempts.get("Brave Search"), "ok")

    def test_monid_without_api_key_is_not_attempted(self):
        """No MONID_API_KEY → is_available() False → the provider is not
        called at all and the chain behaves exactly as before."""
        report, monid_search, brave, _ = self._run_chain(
            monid_available=False,
            monid_links=_monid_links(3),
        )

        monid_search.assert_not_called()
        brave.assert_called_once()
        self.assertNotIn("monid", report["engine"] or "")
        self.assertIn("Brave Search", report["engine"])
        attempts = {
            item["provider"]: item["status"]
            for item in report["strategy"]["provider_attempts"]
        }
        self.assertEqual(attempts.get("monid"), "not_configured")


if __name__ == "__main__":
    unittest.main()
