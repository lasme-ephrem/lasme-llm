import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.memory.database import DatabaseManager


class EditMessageAndTruncateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "memory.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _build_conversation(self):
        session = self.db.create_session()
        roles_contents = [
            ("user", "Première question"),
            ("assistant", "Première réponse"),
            ("user", "Deuxième question"),
            ("assistant", "Deuxième réponse"),
            ("user", "Troisième question"),
            ("assistant", "Troisième réponse"),
        ]
        ids = [
            self.db.add_message(session["id"], role, content)
            for role, content in roles_contents
        ]
        return session, ids

    def test_mid_conversation_edit_updates_content_and_truncates_after(self):
        session, ids = self._build_conversation()
        target_id = ids[2]  # "Deuxième question"

        result = self.db.edit_message_and_truncate(
            session["id"], target_id, "Deuxième question corrigée"
        )

        self.assertTrue(result["updated"])
        self.assertEqual(result["remaining"], 3)
        messages = self.db.get_session_messages(session["id"])
        self.assertEqual(
            [(m["role"], m["content"]) for m in messages],
            [
                ("user", "Première question"),
                ("assistant", "Première réponse"),
                ("user", "Deuxième question corrigée"),
            ],
        )
        self.assertEqual(messages[-1]["id"], target_id)
        self.assertIsNotNone(messages[-1]["edited_at"])

    def test_edit_rejects_assistant_message(self):
        session, ids = self._build_conversation()

        with self.assertRaises(ValueError):
            self.db.edit_message_and_truncate(session["id"], ids[1], "Détournement")

        messages = self.db.get_session_messages(session["id"])
        self.assertEqual(len(messages), 6)

    def test_edit_unknown_message_returns_none(self):
        session, _ = self._build_conversation()

        self.assertIsNone(
            self.db.edit_message_and_truncate(session["id"], "inexistant", "texte")
        )

    def test_edit_rejects_empty_content(self):
        session, ids = self._build_conversation()

        with self.assertRaises(ValueError):
            self.db.edit_message_and_truncate(session["id"], ids[0], "   ")

    def test_equal_timestamps_are_ordered_by_rowid(self):
        session = self.db.create_session()
        with self.db._connection() as conn:
            same_ts = "2026-01-01T12:00:00"
            rows = [
                ("user", "Question A", same_ts),
                ("assistant", "Réponse A", same_ts),
                ("user", "Question B", same_ts),
                ("assistant", "Réponse B", same_ts),
            ]
            ids = []
            for role, content, ts in rows:
                cursor = conn.execute(
                    """
                    INSERT INTO messages (id, session_id, role, content, metadata, timestamp)
                    VALUES (?, ?, ?, ?, '{}', ?)
                    """,
                    (f"m-{len(ids)}", session["id"], role, content, ts),
                )
                ids.append(cursor.lastrowid)
            conn.commit()

        result = self.db.edit_message_and_truncate(
            session["id"], "m-0", "Question A corrigée"
        )

        self.assertEqual(result, {"updated": True, "remaining": 1})
        messages = self.db.get_session_messages(session["id"])
        self.assertEqual(
            [(m["role"], m["content"]) for m in messages],
            [("user", "Question A corrigée")],
        )


class MessageEditEndpointTests(unittest.TestCase):
    def setUp(self):
        from chat.server import main as server_main
        from core.config import settings

        self.server_main = server_main
        self.token = "test-secret-token-very-long-123"
        self.previous_token = settings.access_token
        settings.access_token = self.token
        self.headers = {"X-Lasme-Token": self.token}
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "memory.db")
        self._db_patcher = patch.object(server_main, "db", self.db)
        self._db_patcher.start()
        self.client = TestClient(server_main.app)

    def tearDown(self):
        self.client.close()
        self._db_patcher.stop()
        self.temp_dir.cleanup()
        from core.config import settings

        settings.access_token = self.previous_token

    def test_edit_endpoint_returns_remaining_and_persists(self):
        session = self.db.create_session()
        first = self.db.add_message(session["id"], "user", "Avant")
        second = self.db.add_message(session["id"], "assistant", "Réponse 1")
        target = self.db.add_message(session["id"], "user", "À corriger")
        self.db.add_message(session["id"], "assistant", "Réponse 2")

        response = self.client.post(
            f"/api/sessions/{session['id']}/messages/{target}/edit",
            headers=self.headers,
            json={"content": "Corrigé"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "remaining": 3})
        messages = self.db.get_session_messages(session["id"])
        self.assertEqual([m["id"] for m in messages], [first, second, target])
        self.assertEqual(messages[-1]["content"], "Corrigé")

    def test_edit_endpoint_unknown_session_returns_404(self):
        response = self.client.post(
            "/api/sessions/inexistant/messages/abc/edit",
            headers=self.headers,
            json={"content": "texte"},
        )
        self.assertEqual(response.status_code, 404)

    def test_edit_endpoint_unknown_message_returns_404(self):
        session = self.db.create_session()
        response = self.client.post(
            f"/api/sessions/{session['id']}/messages/inexistant/edit",
            headers=self.headers,
            json={"content": "texte"},
        )
        self.assertEqual(response.status_code, 404)

    def test_edit_endpoint_assistant_message_returns_400(self):
        session = self.db.create_session()
        assistant_id = self.db.add_message(session["id"], "assistant", "Réponse")

        response = self.client.post(
            f"/api/sessions/{session['id']}/messages/{assistant_id}/edit",
            headers=self.headers,
            json={"content": "texte"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
