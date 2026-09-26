"""Recherche web MCP scriptée : routage, repli, format des outils."""

import json
import re
import unittest

from core.agent.tools import ToolRegistry
from core.agent.tools_web import SearchResultNumbering, register_web_tools
from core.mcp.format import format_search_results
from core.mcp.research import research_web
from core.mcp.types import (
    SERVER_BRAVE,
    SERVER_EXA,
    SERVER_FRESHNESS,
    SERVER_TAVILY,
    TOOL_BRAVE_NEWS,
    TOOL_BRAVE_WEB,
    TOOL_EXA_FETCH,
    TOOL_EXA_SEARCH,
    TOOL_SPORTS,
    TOOL_TAVILY_EXTRACT,
    McpCallResult,
    ScriptedMcpClient,
)


def _payload(hits: list[dict]) -> str:
    rows = []
    for hit in hits:
        rows.append(
            {
                "title": hit["title"],
                "url": hit["url"],
                "snippet": hit["snippet"],
                "description": hit["snippet"],
            }
        )
    return json.dumps({"results": rows}, ensure_ascii=False)


def _urls(value) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.extend(re.findall(r"https?://[^\s\)>\]\"']+", value))
        return found
    if isinstance(value, dict):
        url = value.get("url")
        if url:
            found.append(str(url))
        for key in ("results", "hits", "items"):
            nested = value.get(key)
            if nested is not None:
                found.extend(_urls(nested))
        return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_urls(item))
        return found
    url = getattr(value, "url", None)
    if url:
        found.append(str(url))
    return found


class QueryScriptedClient(ScriptedMcpClient):
    """Un texte par requête, sur un seul outil. Les autres répondent ok=False."""

    def __init__(self, by_query: dict, *, server: str, tool: str, available: tuple):
        super().__init__(
            {(server, tool): ""},
            available_servers=available,
        )
        self._by_query = dict(by_query)
        self._server = server
        self._tool = tool

    async def call(self, server_id, tool, arguments, *, timeout_s=45.0):
        del timeout_s
        self.calls.append((server_id, tool, dict(arguments)))
        if server_id == self._server and tool == self._tool:
            blob = " ".join(
                str(value)
                for value in arguments.values()
                if isinstance(value, str)
            ).casefold()
            for key, text in self._by_query.items():
                if key.casefold() in blob:
                    return McpCallResult(
                        ok=True, text=text, server=server_id, tool=tool
                    )
        return McpCallResult(
            ok=False,
            server=server_id,
            tool=tool,
            error=f"outil {tool} non scripté sur {server_id}",
        )


class ResearchWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_unconfigured_search_servers_are_reported(self):
        client = ScriptedMcpClient(available_servers=())
        result = await research_web(client, "prix API LLM")
        self.assertEqual(result["results"], [])
        self.assertTrue(result["errors"])
        self.assertTrue(any("non configuré" in error for error in result["errors"]))
        self.assertIn("exa", result["attempted_servers"])
        self.assertEqual(result["available_servers"], [])

    async def test_sports_query_calls_lookup_and_a_search_engine(self):
        client = ScriptedMcpClient(
            {
                (SERVER_FRESHNESS, TOOL_SPORTS): "vainqueur: France",
                (SERVER_BRAVE, TOOL_BRAVE_WEB): "[]",
                (SERVER_BRAVE, TOOL_BRAVE_NEWS): "[]",
                (SERVER_EXA, TOOL_EXA_SEARCH): "[]",
            },
            available_servers=(SERVER_FRESHNESS, SERVER_BRAVE, SERVER_EXA),
        )
        self.assertTrue(client.available(SERVER_BRAVE))
        self.assertTrue(client.available(SERVER_EXA))
        await research_web(client, "vainqueur de la coupe du monde 2026")
        tools = [tool for _server, tool, _args in client.calls]
        servers = {server for server, _tool, _args in client.calls}
        self.assertIn(TOOL_SPORTS, tools)
        self.assertTrue(servers & {SERVER_BRAVE, SERVER_EXA})

    async def test_failed_server_does_not_drop_other_results(self):
        exa_url = "https://www.bbc.com/isolation-ok"
        failure = McpCallResult(
            ok=False, server=SERVER_BRAVE, tool=TOOL_BRAVE_WEB, error="brave down"
        )
        client = ScriptedMcpClient(
            {
                (SERVER_BRAVE, TOOL_BRAVE_WEB): failure,
                (SERVER_BRAVE, TOOL_BRAVE_NEWS): McpCallResult(
                    ok=False,
                    server=SERVER_BRAVE,
                    tool=TOOL_BRAVE_NEWS,
                    error="brave news down",
                ),
                (SERVER_EXA, TOOL_EXA_SEARCH): _payload(
                    [
                        {
                            "title": "BBC",
                            "url": exa_url,
                            "snippet": "Le fait établi.",
                        }
                    ]
                ),
            },
            available_servers=(SERVER_BRAVE, SERVER_EXA),
        )
        result = await research_web(client, "recette de la tartiflette")
        self.assertTrue(any(server == SERVER_BRAVE for server, _t, _a in client.calls))
        found = _urls(result)
        self.assertTrue(
            any("bbc.com" in url and "isolation-ok" in url for url in found),
            found,
        )


class WebToolOutputTests(unittest.IsolatedAsyncioTestCase):
    def _two_hits(self) -> str:
        return _payload(
            [
                {
                    "title": "Un",
                    "url": "https://exemple.fr/un",
                    "snippet": "extrait un",
                },
                {
                    "title": "Deux",
                    "url": "https://exemple.fr/deux",
                    "snippet": "extrait deux",
                },
            ]
        )

    async def test_web_research_format_and_single_web_read_line(self):
        client = ScriptedMcpClient(
            {(SERVER_BRAVE, TOOL_BRAVE_WEB): self._two_hits()},
            available_servers=(SERVER_BRAVE,),
        )
        registry = ToolRegistry()
        register_web_tools(registry, mcp_client=client)
        result = await registry.execute(
            "web_research", json.dumps({"query": "tartiflette"})
        )
        self.assertTrue(result.ok)
        output = result.output
        self.assertTrue(any("Moteurs:" in line for line in output.splitlines()))
        self.assertIn("[1] Un\n    https://exemple.fr/un\n    extrait un", output)
        self.assertIn("[2] Deux", output)
        self.assertIn("    https://exemple.fr/deux", output)
        self.assertIn("    extrait deux", output)
        self.assertEqual(
            sum(1 for line in output.splitlines() if "web_read" in line),
            1,
        )
        self.assertNotIn("fetch_pages", output)

    async def test_web_research_numbering_continues_on_the_same_registry(self):
        client = QueryScriptedClient(
            {
                "alpha-query": _payload(
                    [
                        {
                            "title": "Alpha",
                            "url": "https://a.example.com/a",
                            "snippet": "extrait alpha",
                        }
                    ]
                ),
                "beta-query": _payload(
                    [
                        {
                            "title": "Beta",
                            "url": "https://b.example.com/b",
                            "snippet": "extrait beta",
                        }
                    ]
                ),
            },
            server=SERVER_BRAVE,
            tool=TOOL_BRAVE_WEB,
            available=(SERVER_BRAVE,),
        )
        registry = ToolRegistry()
        register_web_tools(registry, mcp_client=client)
        numbering = getattr(registry, "web_result_numbering", None)
        self.assertIsInstance(numbering, SearchResultNumbering)
        first = await registry.execute(
            "web_research", json.dumps({"query": "alpha-query"})
        )
        second = await registry.execute(
            "web_research", json.dumps({"query": "beta-query"})
        )
        self.assertIn("[1] Alpha", first.output)
        self.assertIn("[2] Beta", second.output)
        self.assertNotIn("[1]", second.output)
        self.assertGreaterEqual(registry.web_result_numbering.last, 2)

    async def test_web_read_uses_tavily_when_exa_fails(self):
        page = "La page exemple décrit la tartiflette et sa cuisson. " * 8
        self.assertGreater(len(page), 200)
        client = ScriptedMcpClient(
            {
                (SERVER_EXA, TOOL_EXA_FETCH): McpCallResult(
                    ok=False,
                    server=SERVER_EXA,
                    tool=TOOL_EXA_FETCH,
                    error="timeout exa",
                ),
                (SERVER_TAVILY, TOOL_TAVILY_EXTRACT): page,
            },
            available_servers=(SERVER_EXA, SERVER_TAVILY),
        )
        registry = ToolRegistry()
        register_web_tools(registry, mcp_client=client)
        result = await registry.execute(
            "web_read",
            json.dumps({"urls": ["https://exemple.fr"]}),
        )
        self.assertTrue(result.ok)
        self.assertIn("## https://exemple.fr", result.output)
        self.assertRegex(result.output, r"\(\d+ caractères\)")
        self.assertNotIn("ERREUR", result.output)


class FormatSearchResultsTests(unittest.TestCase):
    def test_empty_results_message(self):
        text = format_search_results([])
        self.assertTrue(
            text == "Aucun résultat trouvé sur le Web."
            or text.startswith("Aucun résultat trouvé sur le Web.")
        )

    def test_one_result_opens_a_source_tag(self):
        text = format_search_results(
            [
                {
                    "title": "Titre",
                    "url": "https://exemple.fr/a",
                    "snippet": "extrait court",
                    "engine": "brave",
                }
            ]
        )
        self.assertIn('<source id="1"', text)


if __name__ == "__main__":
    unittest.main()
