import asyncio
import unittest
from typing import Any, Dict, List

from core.agent.registry import build_agent_registry
from core.agent.tools_platform import _format_rag_results
from core.agent.tools_web import _format_search_results, _run_fetch_pages


def _fake_search_fn(query, max_results=None, messages=None, **kwargs):
    return {
        "status": "ok",
        "engine": "test-engine",
        "results": [
            {
                "title": f"Resultat {query}",
                "url": "https://exemple.fr/a",
                "snippet": "Un extrait de preuve.",
            }
        ],
        "errors": [],
    }


def _fake_fetch_fn(url: str) -> str:
    if "404" in url:
        raise RuntimeError("page introuvable")
    return f"# Titre de {url}\nContenu markdown."


class WebToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_applies_recency_and_formats(self):
        registry = build_agent_registry(
            search_fn=_fake_search_fn, fetch_fn=_fake_fetch_fn
        )
        self.assertIn("web_search", registry.names())
        result = await registry.execute(
            "web_search", '{"query": "prix rtx 5090", "recency": "day"}'
        )
        self.assertTrue(result.ok)
        self.assertIn("[1] Resultat prix rtx 5090 (dernières 24 heures)", result.output)
        self.assertIn("https://exemple.fr/a", result.output)
        self.assertIn("Moteur : test-engine", result.output)

    async def test_fetch_pages_batches_and_isolates_errors(self):
        output = await _run_fetch_pages(
            _fake_fetch_fn,
            {"urls": ["https://a.fr", "https://b.fr/404"]},
        )
        self.assertIn("# Titre de https://a.fr", output)
        self.assertIn("ERREUR: RuntimeError", output)
        self.assertIn("https://b.fr/404", output)

    async def test_search_empty_results_message(self):
        text = _format_search_results({"results": [], "errors": ["quota"]})
        self.assertIn("Aucun résultat", text)
        self.assertIn("quota", text)


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
        return build_agent_registry(
            search_fn=_fake_search_fn,
            fetch_fn=_fake_fetch_fn,
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
        registry = build_agent_registry(
            search_fn=_fake_search_fn,
            fetch_fn=_fake_fetch_fn,
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

        registry = build_agent_registry(
            search_fn=_fake_search_fn,
            fetch_fn=_fake_fetch_fn,
            vision_client=FakeVisionClient(),
        )
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
        return build_agent_registry(
            search_fn=_fake_search_fn,
            fetch_fn=_fake_fetch_fn,
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
        registry = build_agent_registry(
            search_fn=_fake_search_fn, fetch_fn=_fake_fetch_fn
        )
        for name in ("artifact_create", "artifact_update", "artifacts_list"):
            self.assertNotIn(name, registry.names())


class UnknownToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tool_lists_available(self):
        registry = build_agent_registry(
            search_fn=_fake_search_fn,
            fetch_fn=_fake_fetch_fn,
            artifact_store=FakeArtifactStore(),
        )
        result = await registry.execute("nope", "{}")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "unknown_tool")
        self.assertIn("available", result.error)
        self.assertIn("artifact_create", result.error)
        self.assertIn("web_search", result.error)


if __name__ == "__main__":
    unittest.main()
