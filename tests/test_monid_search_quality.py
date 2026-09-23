"""Cross-search quality: Monid "armée croisée" (tinyfish + secondary).

All boundaries are mocked (httpx, the provider, the chain, the tool layer):
zero network, zero key. What is exercised:
- ``search_links_cross`` fans out over tinyfish AND the best affordable
  secondary in parallel, merges with normalized-URL dedup and tags each
  link with a distinct ``engine``;
- an over-budget or failing secondary degrades to tinyfish alone, silently;
- ``search_web_detailed`` maps its ``recency`` argument to real
  ``recency_minutes`` and forwards the news vertical + official domains;
- the agent tool threads its ``recency`` enum into the chain.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock
from unittest.mock import AsyncMock, patch

import httpx

from core.tools import monid_provider

API_KEY = "sk-test-secret-123"


class FakeResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class RoutingFakeClient:
    """Offline httpx.AsyncClient: /v1/discover is scripted, /v1/run posts are
    routed by ``provider`` so the two parallel legs resolve independently."""

    def __init__(
        self,
        discover_payload: Dict[str, Any],
        runs: Dict[str, Any],
    ):
        self._discover_payload = discover_payload
        self._runs = runs  # provider -> (status, output_results) | Exception
        self.discover_calls: List[Any] = []
        self.run_calls: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "RoutingFakeClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def post(
        self, url: str, headers: Dict[str, str] | None = None, json: Any = None
    ) -> FakeResponse:
        if url.endswith(monid_provider.DISCOVER_PATH):
            self.discover_calls.append(json)
            return FakeResponse(200, self._discover_payload)
        self.run_calls.append(json)
        scripted = self._runs[json["provider"]]
        if isinstance(scripted, Exception):
            raise scripted
        status, results = scripted
        return FakeResponse(
            200,
            {
                "runId": f"run_{json['provider']}",
                "status": status,
                "output": {"results": results, "total_results": len(results)},
                "price": {"type": "PER_CALL", "amount": {"value": 0, "currency": "USD"}},
                "billedUnits": 0,
            },
        )


def _entry(provider: str, endpoint: str, price: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": provider,
        "endpoint": endpoint,
        "description": "web search",
        "price": price,
        "tags": ["verified"],
        "metrics": {"status": "stable"},
    }


def _discover_payload() -> Dict[str, Any]:
    """tinyfish (free primary) + context.dev (PER_RESULT secondary)."""
    return {
        "results": [
            _entry(
                "tinyfish",
                "/search",
                {"type": "PER_CALL", "amount": {"value": 0, "currency": "USD"}},
            ),
            _entry(
                "context.dev",
                "/web/search",
                {"type": "PER_RESULT", "amount": {"value": 9e-05, "currency": "USD"}},
            ),
            _entry(
                "octen",
                "/search",
                {"type": "PER_CALL", "amount": {"value": 0.001, "currency": "USD"}},
            ),
        ],
        "query": "web search",
        "count": 3,
    }


def _tinyfish_results() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Tinyfish A",
            "url": "https://a.example/page",
            "snippet": "snippet A",
        },
        {
            "title": "Tinyfish B (tracked dup)",
            "url": "https://www.b.example/page?utm_source=x",
            "snippet": "snippet B",
        },
    ]


def _secondary_results() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Context B (same page, no tracking)",
            "url": "https://b.example/page",
            "description": "snippet B from context",
        },
        {
            "title": "Context C",
            "url": "https://c.example/page",
            "description": "snippet C",
        },
    ]


class CrossSearchQualityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._original_env = {
            name: os.environ.get(name)
            for name in ("MONID_API_KEY", "MONID_TIMEOUT_S", "MONID_MAX_PRICE_USD")
        }
        os.environ["MONID_API_KEY"] = API_KEY
        os.environ.pop("MONID_TIMEOUT_S", None)
        os.environ.pop("MONID_MAX_PRICE_USD", None)
        self.addCleanup(self._restore_env)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache_patcher = mock.patch.object(
            monid_provider, "CACHE_PATH", Path(tmp.name) / "monid" / "cache.json"
        )
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)

        poll_patcher = mock.patch.object(monid_provider, "POLL_INTERVAL_S", 0.0)
        poll_patcher.start()
        self.addCleanup(poll_patcher.stop)

    def _restore_env(self):
        for name, value in self._original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def _patch_client(fake: RoutingFakeClient):
        return mock.patch.object(
            monid_provider.httpx, "AsyncClient", lambda **kwargs: fake
        )

    async def test_cross_merges_parallel_legs_with_distinct_engines(self):
        fake = RoutingFakeClient(
            _discover_payload(),
            {
                "tinyfish": ("COMPLETED", _tinyfish_results()),
                "context.dev": ("COMPLETED", _secondary_results()),
            },
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links_cross("world cup final", 5)

        # Both legs ran (parallel POSTs to /v1/run), one discover only.
        self.assertEqual(len(fake.discover_calls), 1)
        self.assertEqual(len(fake.run_calls), 2)
        run_providers = {call["provider"] for call in fake.run_calls}
        self.assertEqual(run_providers, {"tinyfish", "context.dev"})
        tinyfish_call = next(
            call for call in fake.run_calls if call["provider"] == "tinyfish"
        )
        context_call = next(
            call for call in fake.run_calls if call["provider"] == "context.dev"
        )
        self.assertIn("queryParams", tinyfish_call["input"])
        self.assertIn("body", context_call["input"])
        self.assertEqual(context_call["input"]["body"]["numResults"], 10)

        # Dedup on normalized URL (www + tracking + trailing slash), tinyfish
        # first, then the secondary's exclusive hits; distinct engine tags.
        self.assertEqual(
            [link["url"] for link in links],
            [
                "https://a.example/page",
                "https://www.b.example/page?utm_source=x",
                "https://c.example/page",
            ],
        )
        self.assertEqual(
            [link["engine"] for link in links],
            ["monid", "monid", "monid:context.dev"],
        )

    async def test_over_budget_secondary_falls_back_to_tinyfish_only(self):
        os.environ["MONID_MAX_PRICE_USD"] = "0.0001"  # 0.0009 context.dev > cap
        fake = RoutingFakeClient(
            _discover_payload(),
            {"tinyfish": ("COMPLETED", _tinyfish_results())},
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links_cross("q", 5)
        self.assertEqual([link["engine"] for link in links], ["monid", "monid"])
        self.assertEqual(
            {call["provider"] for call in fake.run_calls}, {"tinyfish"}
        )

    async def test_failing_secondary_falls_back_to_tinyfish_only(self):
        fake = RoutingFakeClient(
            _discover_payload(),
            {
                "tinyfish": ("COMPLETED", _tinyfish_results()),
                "context.dev": httpx.ConnectError("secondary down"),
            },
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links_cross("q", 5)
        self.assertEqual(
            [link["engine"] for link in links], ["monid", "monid"]
        )
        self.assertEqual(
            [link["url"] for link in links],
            ["https://a.example/page", "https://www.b.example/page?utm_source=x"],
        )

    async def test_recency_minutes_forwarded_to_both_legs(self):
        fake = RoutingFakeClient(
            _discover_payload(),
            {
                "tinyfish": ("COMPLETED", _tinyfish_results()),
                "context.dev": ("COMPLETED", _secondary_results()),
            },
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links_cross(
                "q", 5, recency_minutes=10080, domain_type="news"
            )
        tinyfish_params = next(
            call for call in fake.run_calls if call["provider"] == "tinyfish"
        )["input"]["queryParams"]
        self.assertEqual(tinyfish_params["recency_minutes"], 10080)
        self.assertEqual(tinyfish_params["domain_type"], "news")
        context_body = next(
            call for call in fake.run_calls if call["provider"] == "context.dev"
        )["input"]["body"]
        self.assertEqual(context_body["freshness"], "last_week")
        # The news hint must not degrade the merged result set.
        self.assertTrue(links)


class ChainRecencyWiringTests(unittest.TestCase):
    """search_web_detailed → search_links_cross wiring (chain fully mocked)."""

    def _run_chain(self, query: str, **chain_kwargs):
        """Run the chain with every provider mocked; return (report, cross)."""
        monid_links = [
            {
                "title": "Spain crowned FIFA World Cup 2026 champions",
                "url": "https://www.fifa.com/tournaments/world-cup/2026/final",
                "snippet": "Spain won the 2026 FIFA World Cup final.",
                "engine": "monid",
            },
            {
                "title": "Context corroboration",
                "url": "https://www.bbc.com/sport/football/2026-final",
                "snippet": "Spain beat Argentina 1-0 after extra time.",
                "engine": "monid:context.dev",
            },
        ]
        cross = AsyncMock(return_value=monid_links)
        with (
            patch.object(monid_provider, "is_available", return_value=True),
            patch.object(monid_provider, "search_links_cross", cross),
            patch.object(
                __import__("core.tools.web_search", fromlist=["settings"]).settings,
                "perplexity_api_key",
                "",
            ),
            patch("core.tools.web_search.settings.search_specialists_enabled", False),
            patch("core.tools.web_search.settings.searxng_enabled", False),
            patch("core.tools.web_search.settings.brave_search_api_key", ""),
            patch("core.tools.web_search.tavily_client", None),
            patch(
                "core.tools.web_search.DDGS",
                side_effect=AssertionError("DuckDuckGo should not run"),
            ),
        ):
            import core.tools.web_search as web_search

            report = web_search.search_web_detailed(query, **chain_kwargs)
        return report, cross

    def test_recency_day_maps_to_1440_minutes(self):
        report, cross = self._run_chain(
            "Qui a remporté la Coupe du monde 2026 ?",
            recency="day",
        )
        kwargs = cross.call_args.kwargs
        self.assertEqual(kwargs.get("recency_minutes"), 1440)
        # Both engines from the cross payload are traceable.
        engines = report["engine"] or ""
        self.assertIn("monid", engines)
        self.assertIn("monid:context.dev", engines)
        self.assertEqual(engines.index("monid"), 0)

    def test_news_vertical_sends_domain_type(self):
        report, cross = self._run_chain(
            "actualités coupe du monde 2026",
        )
        kwargs = cross.call_args.kwargs
        self.assertEqual(kwargs.get("domain_type"), "news")
        # The query hits OFFICIAL_DOMAIN_RULES ("coupe du monde" → fifa.com):
        # the official domain filter is reused as include_domains.
        self.assertEqual(kwargs.get("include_domains"), ["fifa.com"])
        self.assertIn("monid", report["engine"] or "")

    def test_plain_query_sends_neither_filter(self):
        _, cross = self._run_chain("Qui a remporté le Ballon d'Or 2025 ?")
        kwargs = cross.call_args.kwargs
        self.assertIsNone(kwargs.get("recency_minutes"))
        self.assertNotIn("domain_type", kwargs)
        self.assertNotIn("include_domains", kwargs)
        purpose = kwargs.get("purpose") or ""
        self.assertLessEqual(len(purpose), 120)
        self.assertTrue(purpose)


class ToolRecencyThreadingTests(unittest.IsolatedAsyncioTestCase):
    """web_search tool: the ``recency`` enum is threaded into the chain."""

    async def test_tool_recency_day_is_passed_to_chain(self):
        from core.agent.tools_web import _run_web_search

        captured: Dict[str, Any] = {}

        def fake_search_fn(query, max_results=None, messages=None, **kwargs):
            captured["query"] = query
            captured["kwargs"] = kwargs
            return {
                "status": "ok",
                "engine": "monid",
                "results": [
                    {
                        "title": "Résultat",
                        "url": "https://exemple.fr/a",
                        "snippet": "extrait",
                    }
                ],
                "errors": [],
            }

        output = await _run_web_search(
            fake_search_fn,
            {"query": "élection présidentielle", "recency": "day"},
        )
        self.assertEqual(captured["kwargs"].get("recency"), "day")
        self.assertIs(captured["kwargs"].get("force_full_chain"), True)
        self.assertIn("https://exemple.fr/a", output)

        captured.clear()
        await _run_web_search(fake_search_fn, {"query": "théorème de Pythagore"})
        self.assertNotIn("recency", captured["kwargs"])
        self.assertIs(captured["kwargs"].get("force_full_chain"), False)


if __name__ == "__main__":
    unittest.main()
