import asyncio
import json
import unittest

from core.agent.registry import build_agent_registry
from core.agent.tools_web import _format_search_results
from core.mcp.types import (
    SERVER_BRAVE,
    SERVER_EXA,
    SERVER_TAVILY,
    TOOL_BRAVE_WEB,
    TOOL_EXA_FETCH,
    TOOL_TAVILY_EXTRACT,
    McpCallResult,
    ScriptedMcpClient,
)


def _registry(**kwargs):
    kwargs.setdefault("mcp_client", ScriptedMcpClient())
    kwargs.setdefault("web_enabled", True)
    return build_agent_registry(**kwargs)


def _search_payload(title: str, url: str, snippet: str) -> str:
    hit = {
        "title": title,
        "url": url,
        "snippet": snippet,
        "description": snippet,
    }
    return json.dumps({"results": [hit]}, ensure_ascii=False)


class WebToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_research_formats_links(self):
        client = ScriptedMcpClient(
            {
                (SERVER_BRAVE, TOOL_BRAVE_WEB): _search_payload(
                    "Resultat prix rtx 5090",
                    "https://exemple.fr/a",
                    "Un extrait de preuve.",
                )
            },
            available_servers=(SERVER_BRAVE,),
        )
        registry = _registry(mcp_client=client)
        self.assertIn("web_research", registry.names())
        self.assertIn("web_read", registry.names())
        result = await registry.execute(
            "web_research",
            '{"query": "prix rtx 5090", "recency": "day"}',
        )
        self.assertTrue(result.ok)
        self.assertIn("[1] Resultat prix rtx 5090", result.output)
        self.assertIn("https://exemple.fr/a", result.output)
        self.assertIn("Un extrait de preuve.", result.output)
        self.assertTrue(
            any("Moteurs:" in line for line in result.output.splitlines())
        )
        self.assertEqual(
            sum(1 for line in result.output.splitlines() if "web_read" in line),
            1,
        )
        self.assertNotIn("fetch_pages", result.output)
        self.assertNotIn("provider_answer", result.output)

    async def test_web_read_falls_back_to_tavily_when_exa_fails(self):
        page = "Contenu markdown de la page exemple. " * 10
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
        registry = _registry(mcp_client=client)
        result = await registry.execute(
            "web_read",
            json.dumps({"urls": ["https://exemple.fr"]}),
        )
        self.assertTrue(result.ok)
        self.assertIn("## https://exemple.fr", result.output)
        self.assertRegex(result.output, r"\(\d+ caractères\)")
        self.assertNotIn("ERREUR", result.output)

    async def test_search_empty_results_message(self):
        text = _format_search_results({"results": [], "errors": ["quota"]})
        self.assertIn("Recherche Web indisponible", text)
        self.assertIn("quota", text)

    async def test_unconfigured_search_is_a_failed_tool_not_empty_success(self):
        client = ScriptedMcpClient(available_servers=())
        registry = _registry(mcp_client=client)
        result = await registry.execute(
            "web_research",
            json.dumps({"query": "prix API LLM"}),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "execution_error")
        self.assertIn("Recherche Web indisponible", result.error)


class FakeRagStore:
    def search_scopes(self, scopes, query, top_k=4, file_ids=None):
        return [
            {
                "doc_name": "rapport.pdf",
                "page_number": 3,
                "content": "Le chiffre d'affaires augmente de 12%.",
            }
        ]


class FakeRunner:
    class _Result:
        status = "ok"
        exit_code = 0
        duration_ms = 120
        stdout = "8638\n"
        stderr = ""
        files = [{"name": "plot.png"}]

    async def run(self, code, *, timeout_seconds=15, inputs=None):
        self.code = code
        return self._Result()


class FakeFileStore:
    def list(self, project_id):
        return [
            {
                "id": "f1",
                "filename": "notes.txt",
                "mime_type": "text/plain",
                "size": 12,
            }
        ]

    def read(self, file_id):
        return "contenu du fichier".encode()


class PlatformToolsTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self):
        return _registry(
            rag_search_fn=lambda query, top_k: asyncio.sleep(
                0, result=FakeRagStore().search_scopes(["default"], query, top_k)
            ),
            python_runner=FakeRunner(),
            file_store=FakeFileStore(),
            vision_client=None,
        )

    async def test_rag_search_formats_citations(self):
        registry = self._registry()
        result = await registry.execute("rag_search", '{"query": "chiffre affaires"}')
        self.assertTrue(result.ok)
        self.assertIn("[Document : rapport.pdf, p. 3]", result.output)
        self.assertIn("12%", result.output)

    async def test_python_run_reports_stdout_and_files(self):
        registry = self._registry()
        result = await registry.execute(
            "python_run", '{"code": "print(7*1234)"}'
        )
        self.assertTrue(result.ok)
        self.assertIn("stdout", result.output)
        self.assertIn("8638", result.output)
        self.assertIn("plot.png", result.output)

    async def test_files_tools(self):
        registry = self._registry()
        listing = await registry.execute("files_list", "{}")
        self.assertIn("notes.txt", listing.output)
        content = await registry.execute("files_read_text", '{"file_id": "f1"}')
        self.assertIn("contenu du fichier", content.output)

    async def test_vision_tool_absent_without_client(self):
        registry = self._registry()
        self.assertNotIn("analyze_image", registry.names())

    async def test_prebound_image_simplifies_vision_schema(self):
        class FakeVisionClient:
            async def chat(self, model, messages, **kwargs):
                self.messages = messages
                return {"message": {"content": "un carré rouge"}}

        vision = FakeVisionClient()
        registry = _registry(
            vision_client=vision,
            prebound_image="QUJD",  # "ABC" en base64
        )
        tool = registry.get("analyze_image")
        self.assertNotIn("image_base64", tool.parameters["properties"])
        result = await registry.execute(
            "analyze_image", '{"question": "Que vois-tu ?"}'
        )
        self.assertTrue(result.ok)
        self.assertIn("un carré rouge", result.output)
        # L'image pré-liée part bien dans la requête vision.
        parts = vision.messages[0]["content"]
        self.assertIn("QUJD", parts[1]["image_url"]["url"])

    async def test_vision_tool_without_prebound_requires_image(self):
        class FakeVisionClient:
            async def chat(self, model, messages, **kwargs):
                return {"message": {"content": "ok"}}

        registry = _registry(vision_client=FakeVisionClient())
        missing = await registry.execute(
            "analyze_image", '{"question": "Que vois-tu ?"}'
        )
        self.assertFalse(missing.ok)
        self.assertEqual(missing.error_code, "schema_violation")


class FakeArtifactStore:
    def __init__(self):
        self.items = {}

    def create(self, *, project_id, title, content, kind="document", **kwargs):
        artifact_id = f"a{len(self.items) + 1}"
        self.items[artifact_id] = {
            "id": artifact_id, "title": title, "kind": kind,
            "version_number": 1, "project_id": project_id,
        }
        return self.items[artifact_id]

    def add_version(self, artifact_id, content, **kwargs):
        item = self.items.get(artifact_id)
        if item is None:
            return None
        item["version_number"] += 1
        return item

    def list(self, project_id):
        return [
            item for item in self.items.values()
            if item["project_id"] == project_id
        ]


class ArtifactToolsTests(unittest.IsolatedAsyncioTestCase):
    def _registry(self, store):
        return _registry(
            artifact_store=store,
            default_project_id="projet-test",
        )

    async def test_create_list_update_roundtrip(self):
        store = FakeArtifactStore()
        registry = self._registry(store)

        created = await registry.execute(
            "artifact_create",
            '{"title": "Notes de reunion", "content": "# Titre\\nContenu", '
            '"kind": "markdown"}',
        )
        self.assertTrue(created.ok)
        self.assertIn("a1", created.output)
        self.assertIn("markdown", created.output)

        listing = await registry.execute("artifacts_list", "{}")
        self.assertIn("Notes de reunion", listing.output)

        updated = await registry.execute(
            "artifact_update",
            '{"artifact_id": "a1", "content": "# v2", '
            '"change_summary": "relecture"}',
        )
        self.assertTrue(updated.ok)
        self.assertIn("version 2", updated.output)

        missing = await registry.execute(
            "artifact_update", '{"artifact_id": "zz", "content": "x"}'
        )
        self.assertIn("introuvable", missing.output)

    async def test_artifact_tools_absent_without_store(self):
        registry = _registry()
        for name in ("artifact_create", "artifact_update", "artifacts_list"):
            self.assertNotIn(name, registry.names())


class UnknownToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tool_lists_available(self):
        registry = _registry(artifact_store=FakeArtifactStore())
        result = await registry.execute("nope", "{}")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "unknown_tool")
        self.assertIn("available", result.error)
        self.assertIn("artifact_create", result.error)
        self.assertIn("web_research", result.error)


if __name__ == "__main__":
    unittest.main()
