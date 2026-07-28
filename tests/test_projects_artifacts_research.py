import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

from chat.server import main as server_main
from core.artifacts.store import ArtifactStore
from core.files.store import ProjectFileStore
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

    def test_legacy_fable_sessions_are_migrated_to_chat_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "legacy.db"
            manager = DatabaseManager(database_path)
            session = manager.create_session(model="gemma-4-chat")
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "UPDATE sessions SET model = 'gemma-4-fable' "
                    "WHERE id = ?",
                    (session["id"],),
                )
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
            finally:
                connection.close()

            migrated = DatabaseManager(database_path)

            self.assertEqual(
                migrated.get_session(session["id"])["model"],
                "gemma-4-chat",
            )
            connection = sqlite3.connect(database_path)
            try:
                self.assertEqual(
                    connection.execute(
                        "PRAGMA user_version"
                    ).fetchone()[0],
                    2,
                )
            finally:
                connection.close()

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

    def test_project_deletion_cascades_all_project_owned_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "project-cascade.db"
            manager = DatabaseManager(database_path)
            artifacts = ArtifactStore(database_path)
            files = ProjectFileStore(
                db_path=database_path,
                storage_root=root / "originals",
            )
            rag = RAGDocumentStore(database_path)
            project = manager.create_project("Projet jetable")
            session = manager.create_session(
                "Conversation",
                project_id=project["id"],
            )
            manager.add_message(session["id"], "user", "Message privé")
            artifact = artifacts.create(
                project_id=project["id"],
                title="Note",
                content="Contenu privé",
            )
            file_record, _ = files.add(
                project_id=project["id"],
                filename="source.md",
                content=b"# Source\nDonnee privee.",
            )
            rag.add_document(
                project["id"],
                "source.md",
                files.read(file_record["id"]),
                file_id=file_record["id"],
            )

            self.assertTrue(manager.delete_project(project["id"]))
            files.remove_project_storage(project["id"])

            self.assertIsNone(manager.get_project(project["id"]))
            self.assertIsNone(manager.get_session(session["id"]))
            self.assertIsNone(artifacts.get(artifact["id"]))
            self.assertEqual(rag.list_documents(project["id"]), [])
            self.assertIsNone(files.get(file_record["id"]))
            self.assertFalse((root / "originals" / project["id"]).exists())


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


class GenerationPerformanceTests(unittest.TestCase):
    def test_ollama_timings_are_normalized_for_message_metadata(self):
        with patch.object(server_main.time, "monotonic", return_value=102.6):
            stats = server_main.build_generation_stats(
                {
                    "done": True,
                    "prompt_eval_count": 128,
                    "eval_count": 96,
                    "eval_duration": 2_000_000_000,
                    "prompt_eval_duration": 500_000_000,
                    "load_duration": 250_000_000,
                    "total_duration": 2_750_000_000,
                    "done_reason": "stop",
                },
                model="gemma-4-chat",
                started_at=100.0,
                first_content_at=100.42,
            )

        self.assertEqual(stats["model"], "gemma-4-chat")
        self.assertEqual(stats["prompt_tokens"], 128)
        self.assertEqual(stats["output_tokens"], 96)
        self.assertEqual(stats["tokens_per_second"], 48.0)
        self.assertEqual(stats["generation_seconds"], 2.0)
        self.assertEqual(stats["total_seconds"], 2.75)
        self.assertEqual(stats["time_to_first_token"], 0.42)
        self.assertEqual(stats["load_seconds"], 0.25)
        self.assertEqual(stats["prompt_seconds"], 0.5)


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
