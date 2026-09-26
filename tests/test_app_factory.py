"""Smoke tests de la factory applicative (phase A1)."""

import unittest

from chat.server.app import build_capabilities, create_app
from chat.server.deps import Deps


class FakeDB:
    def checkpoint(self):
        self.checked = True


class FakeClient:
    async def list_models(self):
        return [{"name": "gemma-4-12b"}]

    async def aclose(self):
        self.closed = True


class FakeStore:
    def ocr_capabilities(self):
        return {"available": False}


class FakeRunner:
    async def available(self):
        return False


def _fake_deps():
    deps = Deps().bind(
        db=FakeDB(),
        rag_store=FakeStore(),
        project_file_store=FakeStore(),
        artifact_store=FakeStore(),
        python_runner=FakeRunner(),
    )
    deps.bind_client(FakeClient())
    return deps


class AppFactoryTests(unittest.TestCase):
    def test_create_app_wires_all_module_routers(self):
        app = create_app(_fake_deps(), http_dispatch=None)
        self.assertEqual(app.title, "Lasme LLM API")
        served = set()
        for route in app.routes:
            path = getattr(route, "path", None)
            if path:
                served.add(path)
            original = getattr(route, "original_router", None)
            for sub in getattr(original, "routes", None) or []:
                sub_path = getattr(sub, "path", None)
                if sub_path:
                    served.add(sub_path)
        for expected in (
            "/api/chat/stream",
            "/api/sessions",
            "/api/projects",
            "/api/memory",
            "/api/documents/upload",
            "/api/artifacts",
            "/api/runner/status",
            "/api/research/stream",
            "/api/coding/tree",
            "/api/generate-image",
            "/api/health",
        ):
            self.assertIn(expected, served)

    def test_capabilities_reports_the_runtime(self):
        import asyncio
        from unittest.mock import patch

        from core.config import settings

        # La couture historique patch("chat.server.main.client") doit être
        # vue par les services (résolution tardive de Deps.client).
        with patch("chat.server.main.client", FakeClient()):
            caps = asyncio.run(build_capabilities(_fake_deps()))
        self.assertTrue(caps["vision_enabled"])
        # La capacité doit refléter la CONFIG effective (le .env peut activer
        # explicitement la génération d'images externe), pas un défaut figé.
        self.assertEqual(
            caps["external_image_generation_enabled"],
            bool(settings.external_image_generation_enabled),
        )
        self.assertIn("md", caps["supported_project_files"])


if __name__ == "__main__":
    unittest.main()
