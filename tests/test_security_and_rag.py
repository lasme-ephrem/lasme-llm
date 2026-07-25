import tempfile
import unittest
from pathlib import Path

from coding.tools.terminal_tools import _parse_safe_command
from core.config import settings
from core.rag.store import RAGDocumentStore
from core.security import (
    SecurityError,
    resolve_workspace_path,
    validate_public_http_url,
)


class SecurityTests(unittest.TestCase):
    def test_workspace_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_root = settings.workspace_root
            settings.workspace_root = Path(temp_dir).resolve()
            try:
                inside = resolve_workspace_path("folder/file.txt")
                self.assertTrue(inside.is_relative_to(Path(temp_dir).resolve()))
                with self.assertRaises(SecurityError):
                    resolve_workspace_path(Path(temp_dir).resolve().parent / "outside.txt")
            finally:
                settings.workspace_root = previous_root

    def test_private_and_local_urls_are_blocked(self):
        for url in (
            "http://127.0.0.1:11434/api/tags",
            "http://localhost:8000/api/health",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.5/private",
        ):
            with self.subTest(url=url), self.assertRaises(SecurityError):
                validate_public_http_url(url)

    def test_terminal_blocks_shell_control_and_unknown_executables(self):
        with self.assertRaises(SecurityError):
            _parse_safe_command("python -m unittest | powershell")
        with self.assertRaises(SecurityError):
            _parse_safe_command("powershell -Command Get-ChildItem")
        self.assertEqual(
            _parse_safe_command("python -m unittest"),
            ["python", "-m", "unittest"],
        )


class PersistentRAGTests(unittest.TestCase):
    def test_documents_are_persistent_and_isolated_by_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "rag.db"
            store = RAGDocumentStore(db_path)
            added = store.add_document(
                "session-a",
                "notes.md",
                (
                    "# Configuration\n"
                    "Le modèle Fable utilise une quantification Q6_K et Ollama."
                ).encode(),
            )
            self.assertGreater(added, 0)
            self.assertEqual(store.search("session-b", "Fable Ollama"), [])

            reopened = RAGDocumentStore(db_path)
            results = reopened.search("session-a", "Fable Ollama")
            self.assertTrue(results)
            self.assertEqual(results[0]["doc_name"], "notes.md")

            reopened.move_scope("session-a", "session-c")
            self.assertEqual(reopened.search("session-a", "Fable"), [])
            self.assertTrue(reopened.search("session-c", "Fable"))
            self.assertEqual(reopened.clear("session-c"), 1)

    def test_unsupported_document_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            with self.assertRaises(ValueError):
                store.add_document("session", "archive.zip", b"not a document")


if __name__ == "__main__":
    unittest.main()
