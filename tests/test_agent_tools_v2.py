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

    async def test_unknown_tool_lists_available(self):
        registry = self._registry()
        result = await registry.execute("nope", "{}")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "unknown_tool")
        self.assertIn("available", result.error)
        self.assertIn("web_search", result.error)


if __name__ == "__main__":
    unittest.main()
