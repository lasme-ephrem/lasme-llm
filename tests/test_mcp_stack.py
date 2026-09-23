"""Tiers de modèle, catalogue d'outils MCP et garde-fou SQL."""

import json
import unittest

from core.agent.tools import ToolRegistry
from core.agent.tools_mcp_stack import register_mcp_stack
from core.mcp.tiers import model_tier
from core.mcp.types import (
    SERVER_CONTEXT7,
    SERVER_GITHUB,
    SERVER_SQLITE,
    SERVER_TIME,
    TOOL_SQL_READ,
    ScriptedMcpClient,
)


def _stack(model_id: str, *servers: str) -> tuple[ToolRegistry, ScriptedMcpClient]:
    client = ScriptedMcpClient({}, available_servers=servers)
    registry = ToolRegistry()
    register_mcp_stack(registry, mcp_client=client, model_id=model_id)
    return registry, client


class ModelTierTests(unittest.TestCase):
    def test_gemma_ids_map_to_tiers(self):
        self.assertEqual(model_tier("gemma-4-e2b"), "minimal")
        self.assertEqual(model_tier("gemma-4-e4b"), "fast")
        self.assertEqual(model_tier("gemma-4-12b"), "full")
        self.assertEqual(model_tier("gemma-4-12b-256k"), "full")


class RegisterMcpStackTests(unittest.TestCase):
    def test_minimal_e2b_only_exposes_convert_time(self):
        registry, _client = _stack(
            "gemma-4-e2b", SERVER_CONTEXT7, SERVER_TIME
        )
        names = registry.names()
        self.assertIn("convert_time", names)
        self.assertNotIn("library_docs", names)
        self.assertNotIn("github_search", names)

    def test_fast_e4b_exposes_docs_and_time_not_github(self):
        registry, _client = _stack(
            "gemma-4-e4b", SERVER_CONTEXT7, SERVER_TIME
        )
        names = registry.names()
        self.assertIn("library_docs", names)
        self.assertIn("convert_time", names)
        self.assertNotIn("github_search", names)

    def test_full_12b_hides_github_search_when_server_is_down(self):
        registry, _client = _stack(
            "gemma-4-12b", SERVER_CONTEXT7, SERVER_TIME
        )
        self.assertNotIn("github_search", registry.names())

    def test_full_12b_exposes_github_search_only_when_available(self):
        registry, _client = _stack(
            "gemma-4-12b", SERVER_CONTEXT7, SERVER_TIME, SERVER_GITHUB
        )
        self.assertIn("github_search", registry.names())


class QueryDataTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self, client: ScriptedMcpClient) -> ToolRegistry:
        registry = ToolRegistry()
        register_mcp_stack(
            registry, mcp_client=client, model_id="gemma-4-12b"
        )
        return registry

    async def test_writes_are_refused_without_calling_sqlite(self):
        for sql in ("DROP TABLE x", "INSERT INTO t VALUES (1)"):
            with self.subTest(sql=sql):
                client = ScriptedMcpClient(
                    {(SERVER_SQLITE, TOOL_SQL_READ): "secret-rows"}
                )
                registry = self._registry(client)
                result = await registry.execute(
                    "query_data", json.dumps({"sql": sql})
                )
                self.assertEqual(client.calls, [])
                self.assertIn("refus", result.output.casefold())
                self.assertNotIn("secret-rows", result.output)

    async def test_select_calls_sqlite_server(self):
        client = ScriptedMcpClient(
            {(SERVER_SQLITE, TOOL_SQL_READ): "colonne\nada"}
        )
        registry = self._registry(client)
        result = await registry.execute(
            "query_data", json.dumps({"sql": "SELECT 1"})
        )
        self.assertTrue(result.ok)
        self.assertTrue(client.calls)
        server, tool, arguments = client.calls[0]
        self.assertEqual(server, SERVER_SQLITE)
        self.assertEqual(tool, TOOL_SQL_READ)
        self.assertIn("SELECT 1", json.dumps(arguments))
        self.assertIn("ada", result.output)


if __name__ == "__main__":
    unittest.main()
