"""Fusion des hits : dédup URL, plafond par domaine, rang news."""

import unittest
from urllib.parse import urlparse

from core.mcp.merge import SearchHit, merge_hits


def _url(hit) -> str:
    if isinstance(hit, dict):
        return str(hit.get("url") or "")
    return str(getattr(hit, "url", "") or "")


def _engine(hit) -> str:
    value = hit.get("engine") if isinstance(hit, dict) else getattr(hit, "engine", "")
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _hit(title: str, url: str, engine: str, snippet: str = "extrait") -> SearchHit:
    return SearchHit(title=title, url=url, snippet=snippet, engine=engine)


class MergeHitsTests(unittest.TestCase):
    def test_same_url_different_utm_collapses_and_keeps_both_engines(self):
        merged = merge_hits(
            [
                [_hit("Page", "https://exemple.fr/page?utm_source=brave", "brave")],
                [_hit("Page", "https://exemple.fr/page?utm_source=exa", "exa")],
            ],
            "recette de la tartiflette",
            "general",
            limit=5,
        )
        self.assertEqual(len(merged), 1)
        engine = _engine(merged[0]).casefold()
        self.assertIn("brave", engine)
        self.assertIn("exa", engine)

    def test_majority_domain_capped_at_two_when_limit_allows(self):
        merged = merge_hits(
            [
                [
                    _hit("A1", "https://exemple.fr/a", "brave"),
                    _hit("A2", "https://exemple.fr/b", "brave"),
                    _hit("A3", "https://exemple.fr/c", "brave"),
                    _hit("B", "https://autre.fr/z", "exa"),
                ]
            ],
            "recette de la tartiflette",
            "general",
            limit=8,
        )
        hosts = [_host(_url(hit)) for hit in merged]
        self.assertLessEqual(hosts.count("exemple.fr"), 2)
        self.assertIn("autre.fr", hosts)
        self.assertGreaterEqual(len(merged), 2)

    def test_news_query_ranks_bbc_above_bet365(self):
        merged = merge_hits(
            [
                [
                    _hit(
                        "Bet365",
                        "https://www.bet365.com/news/world-cup",
                        "brave",
                        "Article.",
                    ),
                    _hit(
                        "BBC",
                        "https://www.bbc.com/news/world-cup",
                        "exa",
                        "Article.",
                    ),
                ]
            ],
            "dernières actualités en France",
            "news",
            limit=5,
        )
        urls = [_url(hit) for hit in merged]
        bbc = next(index for index, url in enumerate(urls) if "bbc.com" in url)
        bet = next(index for index, url in enumerate(urls) if "bet365" in url)
        self.assertLess(bbc, bet)


if __name__ == "__main__":
    unittest.main()
