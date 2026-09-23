import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.memory.database import DatabaseManager

EVENTS = [
    {"type": "turn_start", "ts": 1.0, "turn": 1},
    {"type": "tool_call", "ts": 1.1, "id": "c1", "name": "calculate",
     "arguments": '{"expression": "2+2"}', "repeat": 1},
    {"type": "tool_result", "ts": 1.2, "id": "c1", "name": "calculate",
     "ok": True, "output": "4", "duration_ms": 3},
    {"type": "final", "ts": 1.5, "content": "2+2 = 4", "done_reason": "stop"},
]


class AgentRunPersistenceTests(unittest.TestCase):
    def test_save_list_get_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = DatabaseManager(Path(temp) / "runs.db")
            run_id = manager.save_agent_run(
                model="gemma-4-e4b",
                prompt="combien font 2+2 ?",
                final_text="2+2 = 4",
                done_reason="stop",
                turns=2,
                events=EVENTS,
                usage={"prompt_tokens": 40, "output_tokens": 12},
            )
            runs = manager.list_agent_runs()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["model"], "gemma-4-e4b")
            self.assertEqual(runs[0]["turns"], 2)

            run = manager.get_agent_run(run_id)
            self.assertEqual(run["final_text"], "2+2 = 4")
            self.assertEqual(len(run["events"]), 4)
            self.assertEqual(run["usage"]["output_tokens"], 12)
            self.assertEqual(run["events"][1]["name"], "calculate")

            self.assertTrue(manager.delete_agent_run(run_id))
            self.assertFalse(manager.delete_agent_run(run_id))
            self.assertIsNone(manager.get_agent_run(run_id))
            self.assertEqual(manager.list_agent_runs(), [])

    def test_prompt_is_truncated_for_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = DatabaseManager(Path(temp) / "runs.db")
            run_id = manager.save_agent_run(
                model="m", prompt="x" * 5_000, final_text="", done_reason="stop",
                turns=1, events=[],
            )
            run = manager.get_agent_run(run_id)
            self.assertEqual(len(run["prompt"]), 2_000)


class AgentRunsApiTests(unittest.TestCase):
    def setUp(self):
        from chat.server import main as server_main
        from core.config import settings
        self.token = "test-secret-token-very-long-123"
        self.previous_token = settings.access_token
        settings.access_token = self.token
        self.headers = {"X-Lasme-Token": self.token}
        self.client = TestClient(server_main.app)
        self.db = server_main.db

    def tearDown(self):
        self.client.close()
        from core.config import settings
        settings.access_token = self.previous_token

    def test_runs_endpoints_roundtrip(self):
        run_id = self.db.save_agent_run(
            model="gemma-4-12b", prompt="mission test", final_text="ok",
            done_reason="stop", turns=1, events=EVENTS, usage={},
        )
        try:
            listing = self.client.get("/api/agent/runs", headers=self.headers)
            self.assertEqual(listing.status_code, 200)
            ids = [run["id"] for run in listing.json()["runs"]]
            self.assertIn(run_id, ids)

            detail = self.client.get(
                f"/api/agent/runs/{run_id}", headers=self.headers
            )
            self.assertEqual(detail.status_code, 200)
            body = detail.json()
            self.assertEqual(body["final_text"], "ok")
            self.assertEqual(len(body["events"]), 4)

            missing = self.client.get(
                "/api/agent/runs/inexistant", headers=self.headers
            )
            self.assertEqual(missing.status_code, 404)
        finally:
            self.db.delete_agent_run(run_id)

    def test_delete_missing_run_returns_404(self):
        response = self.client.delete(
            "/api/agent/runs/inexistant", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
