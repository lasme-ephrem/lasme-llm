"""Le chat principal est agentique : SSE outillé + persistance liée."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ScriptedChatClient:
    def __init__(self, turns):
        self.turns = list(turns)

    async def stream_chat(self, *, model, messages, tools=None, **kwargs):
        self.tools = tools
        for chunk in self.turns.pop(0):
            yield chunk

    async def chat(self, *args, **kwargs):
        return {"message": {"content": ""}}


TOOL_TURN = [
    {
        "message": {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "function": {
                        "name": "calculate",
                        "arguments": '{"expression": "6*7"}',
                    },
                }
            ]
        }
    },
    {
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "tool_calls",
        "eval_count": 10,
        "prompt_eval_count": 20,
    },
]

FINAL_TURN = [
    {"message": {"content": "Le résultat est 42."}},
    {
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
        "eval_count": 8,
        "prompt_eval_count": 30,
    },
]


class AgenticChatStreamTests(unittest.TestCase):
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

    def _run_chat(self, scripted):
        session = self.db.create_session(title="test agent chat")
        with patch(
            "chat.server.main.client", scripted
        ), patch("chat.server.main.search_web_detailed") as mock_search:
            mock_search.return_value = {"results": [], "errors": []}
            response = self.client.post(
                "/api/chat/stream",
                headers=self.headers,
                json={
                    "session_id": session["id"],
                    "model": "gemma-4-e4b",
                    "messages": [
                        {"role": "user", "content": "Combien font 6*7 ?"}
                    ],
                    "web_search_enabled": False,
                    "web_search_mode": "off",
                },
            )
            self.assertEqual(response.status_code, 200)
            events = []
            for line in response.text.splitlines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    events.append(json.loads(line[6:]))
        return session["id"], events

    def test_tool_flow_reaches_sse_and_persists_run(self):
        scripted = ScriptedChatClient([list(TOOL_TURN), list(FINAL_TURN)])
        session_id, events = self._run_chat(scripted)
        try:

            types = [event.get("type") for event in events]
            self.assertIn("agent_tool_call", types)
            self.assertIn("agent_tool_result", types)
            self.assertIn("content_delta", types)
            self.assertIn("message_saved", types)
            self.assertIn("generation_stats", types)

            call = next(e for e in events if e["type"] == "agent_tool_call")
            self.assertEqual(call["name"], "calculate")
            result = next(e for e in events if e["type"] == "agent_tool_result")
            self.assertTrue(result["ok"])
            self.assertEqual(result["output"], "42")

            # Le modèle a bien reçu la palette d'outils du chat.
            self.assertIsNotNone(getattr(scripted, "tools", None))
            tool_names = {t["function"]["name"] for t in scripted.tools}
            self.assertIn("web_search", tool_names)
            self.assertIn("rag_search", tool_names)

            content = "".join(
                e.get("content", "") for e in events if e["type"] == "content_delta"
            )
            self.assertIn("42", content)

            # Persistance : message assistant lié à un run agent.
            messages = self.db.get_session_messages(session_id)
            assistant = [m for m in messages if m["role"] == "assistant"][-1]
            self.assertIn("42", assistant["content"])
            metadata = assistant.get("metadata") or {}
            agent_meta = metadata.get("agent") or {}
            self.assertIn("calculate", agent_meta.get("tools", []))
            run = self.db.get_agent_run(agent_meta["run_id"])
            self.assertIsNotNone(run)
            self.assertEqual(run["turns"], 2)
            self.db.delete_agent_run(agent_meta["run_id"])
        finally:
            self.db.delete_session(session_id)

    def test_plain_answer_without_tools_still_works(self):
        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, events = self._run_chat(scripted)
        try:
            types = [event.get("type") for event in events]
            self.assertIn("content_delta", types)
            self.assertIn("generation_stats", types)
            self.assertNotIn("agent_tool_call", types)
            messages = self.db.get_session_messages(session_id)
            assistant = [m for m in messages if m["role"] == "assistant"][-1]
            self.assertIn("42", assistant["content"])
        finally:
            self.db.delete_session(session_id)


if __name__ == "__main__":
    unittest.main()
