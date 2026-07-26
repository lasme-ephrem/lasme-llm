import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from chat.server import main as server_main
from core.artifacts.store import ArtifactStore
from core.memory.database import (
    DEFAULT_PROJECT_DESCRIPTION,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_NAME,
    DatabaseManager,
)
from core.rag.store import RAGDocumentStore
from core.research.service import build_research_plan, merge_research_results


class ProjectConversationTests(unittest.TestCase):
    def test_primary_project_identity_is_immutable_except_for_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DatabaseManager(Path(temp_dir) / "projects.db")

            project = manager.update_project(
                DEFAULT_PROJECT_ID,
                name="Projet renommé",
                description="Description remplacée",
                instructions="Instruction remplacée",
                default_model="gemma-4-fable",
                memory_mode="off",
            )

            self.assertIsNotNone(project)
            self.assertEqual(project["name"], DEFAULT_PROJECT_NAME)
            self.assertEqual(
                project["description"],
                DEFAULT_PROJECT_DESCRIPTION,
            )
            self.assertEqual(project["instructions"], "")
            self.assertEqual(project["default_model"], "gemma-4-chat")
            self.assertEqual(project["memory_mode"], "off")
            self.assertFalse(manager.delete_project(DEFAULT_PROJECT_ID))

    def test_project_isolation_and_non_destructive_branch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DatabaseManager(Path(temp_dir) / "projects.db")
            project = manager.create_project(
                "Recherche",
                instructions="Toujours citer les documents.",
                memory_mode="project",
            )
            source = manager.create_session(
                title="Original",
                model="gemma-4-chat",
                project_id=project["id"],
            )
            user_id = manager.add_message(
                source["id"],
                "user",
                "Explique la première version.",
            )
            manager.add_message(source["id"], "assistant", "Première réponse.")

            branch = manager.branch_session(
                source["id"],
                user_id,
                replacement_content="Explique la version corrigée.",
            )

            original_messages = manager.get_session_messages(source["id"])
            branch_messages = manager.get_session_messages(branch["id"])
            self.assertEqual(original_messages[0]["content"], "Explique la première version.")
            self.assertEqual(branch_messages[0]["content"], "Explique la version corrigée.")
            self.assertEqual(branch["project_id"], project["id"])
            self.assertEqual(branch["parent_session_id"], source["id"])


class TemporaryConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_temporary_chat_never_persists_or_reads_memory(self):
        async def fake_stream_chat(**_kwargs):
            yield {"message": {"content": "Réponse temporaire."}}
            yield {
                "done": True,
                "eval_count": 2,
                "eval_duration": 1_000_000_000,
            }

        request = server_main.ChatRequest(
            project_id=DEFAULT_PROJECT_ID,
            messages=[
                server_main.ChatMessage(
                    role="user",
                    content="Réponds sans conserver cet échange.",
                )
            ],
            web_search_enabled=False,
            web_search_mode="off",
            intelligence_level="fast",
            temporary=True,
        )

        with (
            patch.object(
                server_main,
                "detect_image_intent",
                new=AsyncMock(
                    return_value={"is_image": False, "prompt": ""}
                ),
            ),
            patch.object(
                server_main.client,
                "stream_chat",
                new=fake_stream_chat,
            ),
            patch.object(server_main.db, "create_session") as create_session,
            patch.object(server_main.db, "add_message") as add_message,
            patch.object(
                server_main.db,
                "get_session_memory",
            ) as get_session_memory,
            patch.object(
                server_main.db,
                "list_personal_memories",
            ) as list_personal_memories,
            patch.object(
                server_main.rag_store,
                "count_chunks",
            ) as count_chunks,
        ):
            response = await server_main.chat_stream(request)
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(
                    chunk.decode("utf-8")
                    if isinstance(chunk, bytes)
                    else str(chunk)
                )

        payload = "".join(chunks)
        self.assertIn('"temporary": true', payload)
        self.assertIn('"type": "content_delta"', payload)
        self.assertIn("R\\u00e9ponse temporaire.", payload)
        create_session.assert_not_called()
        add_message.assert_not_called()
        get_session_memory.assert_not_called()
        list_personal_memories.assert_not_called()
        count_chunks.assert_not_called()


class ArtifactTests(unittest.TestCase):
    def test_artifact_versions_are_immutable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArtifactStore(Path(temp_dir) / "artifacts.db")
            artifact = store.create(
                project_id="default",
                title="Rapport",
                content="Version initiale",
                kind="research",
            )
            updated = store.add_version(
                artifact["id"],
                "Version révisée",
                change_summary="Correction des chiffres",
                kind="document",
            )

            self.assertEqual(updated["current_version"], 2)
            self.assertEqual(updated["content"], "Version révisée")
            self.assertEqual(updated["kind"], "document")
            self.assertEqual(updated["versions"][1]["content"], "Version initiale")


class HybridRAGTests(unittest.TestCase):
    def test_results_include_precise_chunk_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "hybrid.db")
            store.add_document(
                "project-a",
                "architecture.md",
                (
                    "L'orchestrateur choisit automatiquement le modèle local "
                    "selon la complexité de la demande."
                ).encode("utf-8"),
            )
            results = store.search(
                "project-a",
                "orchestration automatique des modèles",
            )
            self.assertTrue(results)
            self.assertEqual(results[0]["page"], 1)
            self.assertIn("chunk_id", results[0])
            self.assertIn("vector_score", results[0])


class DeepResearchPlanningTests(unittest.TestCase):
    def test_plan_is_bounded_and_evidence_is_deduplicated(self):
        plan = build_research_plan("Compare deux solutions actuelles")
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]["id"], "primary")

        merged = merge_research_results(
            [
                {
                    "results": [
                        {
                            "url": "https://example.com/report?utm_source=x",
                            "title": "Premier",
                            "score": 0.2,
                        }
                    ]
                },
                {
                    "results": [
                        {
                            "url": "https://example.com/report?ref=home",
                            "title": "Meilleur",
                            "score": 0.9,
                            "verified": True,
                        }
                    ]
                },
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "Meilleur")


if __name__ == "__main__":
    unittest.main()
