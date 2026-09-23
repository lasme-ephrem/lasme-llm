"""Offline tests for the Monid gateway provider (mocked httpx, no network).

Covers the verified live contract: discover → run (200 synchronous or
202 + polling), endpoint disk cache, price guardrail and key redaction.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union
from unittest import mock

import httpx

from core.tools import monid_provider

API_KEY = "sk-test-secret-123"

ScriptedResponse = Union["FakeResponse", Exception]


class FakeResponse:
    """Minimal stand-in for an httpx response."""

    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class FakeAsyncClient:
    """Offline stand-in for ``httpx.AsyncClient``.

    Replays the scripted responses in order; once exhausted, the last one is
    replayed indefinitely (convenient for cache/polling scenarios).
    """

    def __init__(
        self,
        post_responses: Sequence[ScriptedResponse] = (),
        get_responses: Sequence[ScriptedResponse] = (),
    ):
        self.post_calls: List[Dict[str, Any]] = []
        self.get_calls: List[Dict[str, Any]] = []
        self._post_responses: List[ScriptedResponse] = list(post_responses)
        self._get_responses: List[ScriptedResponse] = list(get_responses)

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    @staticmethod
    def _next(scripted: List[ScriptedResponse]) -> ScriptedResponse:
        if not scripted:
            raise AssertionError("no scripted response left")
        if len(scripted) == 1:
            return scripted[0]
        return scripted.pop(0)

    async def post(
        self, url: str, headers: Dict[str, str] | None = None, json: Any = None
    ) -> FakeResponse:
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        item = self._next(self._post_responses)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url: str, headers: Dict[str, str] | None = None) -> FakeResponse:
        self.get_calls.append({"url": url, "headers": headers})
        item = self._next(self._get_responses)
        if isinstance(item, Exception):
            raise item
        return item


def _free_price() -> Dict[str, Any]:
    return {"type": "PER_CALL", "amount": {"value": 0.0, "currency": "USD"}}


def _discover_response(
    provider: str = "tinyfish",
    endpoint: str = "/search",
    price: Dict[str, Any] | None = None,
) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "results": [
                {
                    "provider": provider,
                    "providerName": provider,
                    "endpoint": endpoint,
                    "description": "web search",
                    "price": price if price is not None else _free_price(),
                    "score": 0.9,
                    "tags": ["verified"],
                    "metrics": {
                        "status": "stable",
                        "runTimeMs": {"p50": 800, "p95": 2000},
                    },
                    "hints": {},
                }
            ],
            "query": "tinyfish",
            "count": 1,
        },
    )


def _run_response(
    results: List[Dict[str, Any]],
    run_id: str = "run_1",
    status: str = "COMPLETED",
) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "runId": run_id,
            "status": status,
            "output": {
                "page": 0,
                "query": "q",
                "results": results,
                "total_results": len(results),
            },
            "price": _free_price(),
            # Deliberately unreliable: the provider must use len(output.results).
            "billedUnits": 0,
            "resultCount": 0,
        },
    )


class AvailabilityTests(unittest.TestCase):
    def test_unavailable_without_key(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": ""}):
            self.assertFalse(monid_provider.is_available())

    def test_available_with_key(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": API_KEY}):
            self.assertTrue(monid_provider.is_available())


class MonidEnvMixin(unittest.IsolatedAsyncioTestCase):
    """Hermetic env + tmp disk cache shared by all Monid test classes."""

    def setUp(self):
        # Hermetic env: key set, knobs reset.
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
        self.cache_path = Path(tmp.name) / "monid" / "endpoint_cache.json"
        cache_patcher = mock.patch.object(monid_provider, "CACHE_PATH", self.cache_path)
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

    def _patch_client(self, fake: FakeAsyncClient):
        return mock.patch.object(
            monid_provider.httpx, "AsyncClient", lambda **kwargs: fake
        )


class MonidSearchTests(MonidEnvMixin):

    async def test_run_200_completed_maps_and_slices(self):
        raw = [
            {"title": "T" * 300, "url": f"https://example.net/{i}", "snippet": "S" * 700}
            for i in range(9)
        ]
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response(raw)]
        )
        with self._patch_client(fake), self.assertLogs("Monid", level="INFO") as logs:
            links = await monid_provider.search_links("test query", 3)
        self.assertEqual(len(links), 3)
        for i, link in enumerate(links):
            self.assertEqual(link["url"], f"https://example.net/{i}")
            self.assertEqual(link["title"], "T" * 200)
            self.assertEqual(link["snippet"], "S" * 600)
        # INFO run log with provider, endpoint, price and billed units.
        joined = "\n".join(logs.output)
        self.assertIn("[monid] run ok", joined)
        self.assertIn("provider=tinyfish", joined)
        self.assertIn("endpoint=/search", joined)
        self.assertIn("billed_units=0", joined)
        # Run request body matches the live contract.
        body = fake.post_calls[1]["json"]
        self.assertEqual(body["provider"], "tinyfish")
        self.assertEqual(body["endpoint"], "/search")
        self.assertEqual(body["input"]["queryParams"]["query"], "test query")
        purpose = body["input"]["queryParams"]["purpose"]
        self.assertTrue(purpose.startswith("web search for:"))
        self.assertLessEqual(len(purpose), 200)
        self.assertEqual(
            fake.post_calls[1]["headers"]["Authorization"], f"Bearer {API_KEY}"
        )

    def test_sync_bridge_returns_links(self):
        fake = FakeAsyncClient(
            post_responses=[
                _discover_response(),
                _run_response([{"title": "T", "url": "https://s.fr/a", "snippet": "s"}]),
            ]
        )
        with self._patch_client(fake):
            links = monid_provider.search_links_sync("bridge", 5)
        self.assertEqual(links[0]["url"], "https://s.fr/a")

    # --- 3/4. Asynchronous 202 run + polling --------------------------------

    async def test_run_202_polls_until_completed(self):
        results = [{"title": "T", "url": "https://a.fr/x", "snippet": "s"}]
        fake = FakeAsyncClient(
            post_responses=[
                _discover_response(),
                FakeResponse(202, {"runId": "run_9"}),
            ],
            get_responses=[_run_response(results, run_id="run_9")],
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("async q", 5)
        self.assertEqual(links[0]["url"], "https://a.fr/x")
        self.assertTrue(fake.get_calls[0]["url"].endswith("/v1/runs/run_9"))
        self.assertEqual(
            fake.get_calls[0]["headers"]["Authorization"], f"Bearer {API_KEY}"
        )

    async def test_run_202_poll_failed_returns_empty(self):
        fake = FakeAsyncClient(
            post_responses=[
                _discover_response(),
                FakeResponse(202, {"runId": "run_9"}),
            ],
            get_responses=[FakeResponse(200, {"runId": "run_9", "status": "FAILED"})],
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("async q", 5)
        self.assertEqual(links, [])

    # --- 5. Network / server errors -----------------------------------------

    async def test_network_error_returns_empty(self):
        fake = FakeAsyncClient(post_responses=[httpx.ConnectError("boom")])
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links, [])

    async def test_http_500_returns_empty(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), FakeResponse(500, {"detail": "boom"})]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links, [])

    # --- 6. Endpoint disk cache ----------------------------------------------

    async def test_endpoint_cached_discover_called_once(self):
        results = [{"title": "T", "url": "https://c.fr/a", "snippet": "s"}]
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response(results)]
        )
        with self._patch_client(fake):
            first = await monid_provider.search_links("first", 5)
            second = await monid_provider.search_links("second", 5)
        discovers = [
            call
            for call in fake.post_calls
            if call["url"].endswith(monid_provider.DISCOVER_PATH)
        ]
        self.assertEqual(len(discovers), 1)
        self.assertEqual(len(fake.post_calls), 3)  # discover + 2 runs
        self.assertEqual(first[0]["url"], "https://c.fr/a")
        self.assertEqual(second[0]["url"], "https://c.fr/a")
        self.assertTrue(self.cache_path.exists())
        saved = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["provider"], "tinyfish")
        self.assertEqual(saved["endpoint"], "/search")
        self.assertIn("price", saved)
        self.assertIn("cached_at", saved)

    async def test_cache_expiry_triggers_new_discover(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {
                    "provider": "tinyfish",
                    "endpoint": "/search",
                    "price": _free_price(),
                    "cached_at": time.time() - monid_provider.CACHE_TTL_S - 10,
                }
            ),
            encoding="utf-8",
        )
        results = [{"title": "T", "url": "https://e.fr/a", "snippet": "s"}]
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response(results)]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        discovers = [
            call
            for call in fake.post_calls
            if call["url"].endswith(monid_provider.DISCOVER_PATH)
        ]
        self.assertEqual(len(discovers), 1)
        self.assertEqual(links[0]["url"], "https://e.fr/a")

    # --- 7. Price guardrail ---------------------------------------------------

    async def test_price_cap_refuses_expensive_endpoint(self):
        os.environ["MONID_MAX_PRICE_USD"] = "0.01"
        price = {"type": "PER_CALL", "amount": {"value": 0.05, "currency": "USD"}}
        fake = FakeAsyncClient(post_responses=[_discover_response(price=price)])
        with self._patch_client(fake), self.assertLogs("Monid", level="WARNING") as logs:
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links, [])
        runs = [
            call for call in fake.post_calls if call["url"].endswith(monid_provider.RUN_PATH)
        ]
        self.assertEqual(runs, [])
        self.assertTrue(any("exceeds" in message for message in logs.output))

    async def test_price_cap_multiplies_per_result_pricing(self):
        os.environ["MONID_MAX_PRICE_USD"] = "0.01"
        price = {"type": "PER_RESULT", "amount": {"value": 0.004, "currency": "USD"}}
        fake = FakeAsyncClient(post_responses=[_discover_response(price=price)])
        with self._patch_client(fake), self.assertLogs("Monid", level="WARNING"):
            # 0.004 x 5 = 0.02 USD > 0.01 USD cap → refused.
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links, [])

    async def test_price_cap_falls_back_to_cheaper_endpoint(self):
        os.environ["MONID_MAX_PRICE_USD"] = "0.01"
        expensive = {"type": "PER_CALL", "amount": {"value": 0.05, "currency": "USD"}}
        discover = FakeResponse(
            200,
            {
                "results": [
                    {
                        "provider": "tinyfish",
                        "endpoint": "/search",
                        "price": expensive,
                        "tags": ["verified"],
                        "metrics": {"status": "stable"},
                    },
                    {
                        "provider": "otherco",
                        "endpoint": "/websearch",
                        "price": _free_price(),
                        "tags": ["verified"],
                        "metrics": {"status": "stable"},
                    },
                ]
            },
        )
        fake = FakeAsyncClient(
            post_responses=[
                discover,
                _run_response([{"title": "T", "url": "https://ok.fr/a", "snippet": "s"}]),
            ]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links[0]["url"], "https://ok.fr/a")
        body = fake.post_calls[1]["json"]
        self.assertEqual(body["provider"], "otherco")
        self.assertEqual(body["endpoint"], "/websearch")

    async def test_prefers_tinyfish_search_endpoint(self):
        discover = FakeResponse(
            200,
            {
                "results": [
                    {
                        "provider": "otherco",
                        "endpoint": "/websearch",
                        "price": _free_price(),
                        "tags": ["verified"],
                        "metrics": {"status": "stable"},
                    },
                    {
                        "provider": "tinyfish",
                        "endpoint": "/search",
                        "price": {
                            "type": "PER_CALL",
                            "amount": {"value": 0.001, "currency": "USD"},
                        },
                        "tags": ["verified"],
                        "metrics": {"status": "stable"},
                    },
                ]
            },
        )
        fake = FakeAsyncClient(
            post_responses=[
                discover,
                _run_response([{"title": "T", "url": "https://t.fr/a", "snippet": "s"}]),
            ]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links[0]["url"], "https://t.fr/a")
        body = fake.post_calls[1]["json"]
        self.assertEqual(body["provider"], "tinyfish")
        self.assertEqual(body["endpoint"], "/search")

    # --- 8. The API key never reaches logs -----------------------------------

    async def test_api_key_never_reaches_logs(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), FakeResponse(500, {"detail": "boom"})]
        )
        with self._patch_client(fake), self.assertLogs(level="DEBUG") as logs:
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links, [])
        joined = "\n".join(logs.output)
        self.assertNotIn(API_KEY, joined)
        self.assertNotIn("Bearer", joined)


class MonidRichParamsTests(MonidEnvMixin):
    """Rich tinyfish /search params forwarded (or safely dropped) in
    ``input.queryParams`` — a bad caller hint can never break the search."""

    async def test_every_rich_param_is_forwarded(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response([])]
        )
        with self._patch_client(fake):
            await monid_provider.search_links(
                "robotaxi news",
                5,
                purpose="follow Robotaxi announcements",
                domain_type="news",
                include_domains=["reuters.com", "bloomberg.com"],
                exclude_domains=["pinterest.com"],
                recency_minutes=10080,
                language="fr",
                page=2,
            )
        params = fake.post_calls[1]["json"]["input"]["queryParams"]
        self.assertEqual(params["query"], "robotaxi news")
        self.assertEqual(params["purpose"], "follow Robotaxi announcements")
        self.assertEqual(params["domain_type"], "news")
        self.assertEqual(params["include_domains"], ["reuters.com", "bloomberg.com"])
        self.assertEqual(params["exclude_domains"], ["pinterest.com"])
        self.assertEqual(params["recency_minutes"], 10080)
        self.assertEqual(params["language"], "fr")
        self.assertEqual(params["page"], 2)

    async def test_invalid_params_are_ignored_not_sent(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response([])]
        )
        with self._patch_client(fake), self.assertLogs("Monid", level="INFO"):
            await monid_provider.search_links(
                "q",
                5,
                domain_type="dark_web",
                recency_minutes=-30,
                include_domains=["  ", ""],
                page=99,  # clamped to the contract range 0..10
            )
        params = fake.post_calls[1]["json"]["input"]["queryParams"]
        self.assertNotIn("domain_type", params)
        self.assertNotIn("recency_minutes", params)
        self.assertNotIn("include_domains", params)
        self.assertEqual(params["page"], 10)

    async def test_legacy_positional_call_still_works(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response([])]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("plain query", 4)
        self.assertEqual(links, [])
        params = fake.post_calls[1]["json"]["input"]["queryParams"]
        self.assertEqual(set(params), {"query", "purpose"})
        self.assertTrue(params["purpose"].startswith("web search for:"))

    async def test_empty_purpose_falls_back_to_derivation(self):
        fake = FakeAsyncClient(
            post_responses=[_discover_response(), _run_response([])]
        )
        with self._patch_client(fake):
            await monid_provider.search_links("q", 5, purpose="   ")
        params = fake.post_calls[1]["json"]["input"]["queryParams"]
        self.assertEqual(params["purpose"], "web search for: q")

    async def test_octen_nested_results_are_extracted(self):
        fake = FakeAsyncClient(
            post_responses=[
                _discover_response(),
                FakeResponse(
                    200,
                    {
                        "runId": "run_oct",
                        "status": "COMPLETED",
                        "output": {
                            "data": {
                                "query": "q",
                                "results": [
                                    {
                                        "title": "Octen hit",
                                        "url": "https://octen.example/a",
                                        "highlight": "body text",
                                    }
                                ],
                            }
                        },
                        "price": {
                            "type": "PER_CALL",
                            "amount": {"value": 0.001, "currency": "USD"},
                        },
                        "billedUnits": 1,
                    },
                ),
            ]
        )
        with self._patch_client(fake):
            links = await monid_provider.search_links("q", 5)
        self.assertEqual(links[0]["url"], "https://octen.example/a")
        self.assertEqual(links[0]["snippet"], "body text")


if __name__ == "__main__":
    unittest.main()
