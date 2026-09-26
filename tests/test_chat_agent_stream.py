"""Le chat principal est agentique : SSE outillé + persistance liée."""

import json
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class ScriptedChatClient:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen_messages = []

    async def stream_chat(self, *, model, messages, tools=None, **kwargs):
        self.tools = tools
        self.seen_messages.append(list(messages))
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

NARRATION_TURN = [
    {"message": {"content": "Je vérifie le calcul "}},
    {"message": {"content": "avant de répondre."}},
    *TOOL_TURN,
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

    def _run_chat(self, scripted, *, web_mode="auto", web_enabled=True):
        session = self.db.create_session(title="test agent chat")
        with patch("chat.server.main.client", scripted):
            response = self.client.post(
                "/api/chat/stream",
                headers=self.headers,
                json={
                    "session_id": session["id"],
                    "model": "gemma-4-e4b",
                    "messages": [
                        {"role": "user", "content": "Combien font 6*7 ?"}
                    ],
                    "web_search_enabled": web_enabled,
                    "web_search_mode": web_mode,
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

            # Le modèle a bien reçu la palette d'outils du chat (mode auto).
            self.assertIsNotNone(getattr(scripted, "tools", None))
            tool_names = {t["function"]["name"] for t in scripted.tools}
            self.assertIn("web_research", tool_names)
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

    def test_web_off_mode_removes_web_tools_from_registry(self):
        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, _events = self._run_chat(
            scripted, web_mode="off", web_enabled=False
        )
        try:
            tool_names = {t["function"]["name"] for t in scripted.tools or []}
            self.assertNotIn("web_research", tool_names)
            self.assertNotIn("web_read", tool_names)
            # Les autres outils restent disponibles.
            self.assertIn("calculate", tool_names)
            self.assertIn("rag_search", tool_names)
        finally:
            self.db.delete_session(session_id)

    def test_narration_before_tool_call_is_kept_as_preamble(self):
        scripted = ScriptedChatClient([list(NARRATION_TURN), list(FINAL_TURN)])
        session_id, events = self._run_chat(scripted)
        try:
            types = [event.get("type") for event in events]
            self.assertIn("content_reset", types)
            self.assertIn("content_replace", types)

            # Streaming réel : la narration part AVANT l'appel d'outil.
            self.assertLess(
                types.index("content_delta"),
                types.index("agent_tool_call"),
            )
            reset = next(e for e in events if e["type"] == "content_reset")
            self.assertIn("avant de répondre", reset["text"])
            self.assertEqual(reset.get("reason"), "tool_call")

            # La narration est archivée, jamais collée à la réponse.
            replace = next(e for e in events if e["type"] == "content_replace")
            self.assertIn("42", replace["text"])
            self.assertNotIn("avant de répondre", replace["text"])
            messages = self.db.get_session_messages(session_id)
            assistant = [m for m in messages if m["role"] == "assistant"][-1]
            self.assertEqual(assistant["content"], replace["text"])
            self.assertNotIn("avant de répondre", assistant["content"])
        finally:
            self.db.delete_session(session_id)

    def test_content_replace_matches_persisted_message(self):
        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, events = self._run_chat(scripted)
        try:
            replace = next(e for e in events if e["type"] == "content_replace")
            messages = self.db.get_session_messages(session_id)
            assistant = [m for m in messages if m["role"] == "assistant"][-1]
            self.assertEqual(replace["text"], assistant["content"])
        finally:
            self.db.delete_session(session_id)

    def test_citation_directive_lives_in_the_system_prompt(self):
        # Les consignes de rédaction/citation ne doivent JAMAIS être collées
        # au message utilisateur : le modèle les prenait pour des instructions
        # émanant de l'utilisateur et perdait la demande réelle de vue.
        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, _events = self._run_chat(scripted)
        try:
            seen = scripted.seen_messages[0]
            system_content = "\n".join(
                str(message.get("content") or "")
                for message in seen
                if message.get("role") == "system"
            )
            user_content = "\n".join(
                str(message.get("content") or "")
                for message in seen
                if message.get("role") == "user"
            )
            self.assertIn("marqueurs numériques", system_content)
            self.assertNotIn("marqueurs numériques", user_content)
            self.assertIn("Combien font 6*7", user_content)
        finally:
            self.db.delete_session(session_id)

    def test_budget_retry_ranges_draft_without_duplicating(self):
        # Un tour tronqué (budget dépassé) est RE-STREAMÉ par l'orchestrateur :
        # le brouillon tronqué doit être rangé (reason budget_retried), sinon
        # il s'accumule avec sa relance dans la réponse.
        truncated = [
            {"message": {"content": "Début de réponse tronqu"}},
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "length",
                "finish_reason": "length",
                "eval_count": 8,
                "prompt_eval_count": 30,
            },
        ]
        scripted = ScriptedChatClient([list(truncated), list(FINAL_TURN)])
        session_id, events = self._run_chat(scripted)
        try:
            resets = [e for e in events if e["type"] == "content_reset"]
            self.assertTrue(resets, "le brouillon tronqué doit être rangé")
            self.assertEqual(resets[-1].get("reason"), "budget_retried")
            self.assertIn("tronqu", resets[-1]["text"])
            messages = self.db.get_session_messages(session_id)
            assistant = [m for m in messages if m["role"] == "assistant"][-1]
            self.assertNotIn("tronqu", assistant["content"])
            self.assertEqual(
                assistant["content"].count("Le résultat est 42."), 1
            )
        finally:
            self.db.delete_session(session_id)

    def test_prompt_forbids_drafting_before_tool_calls(self):
        from core.agent.prompts import TURN_DISCIPLINE_RULE

        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, _events = self._run_chat(scripted)
        try:
            system_contents = [
                str(message.get("content") or "")
                for message in scripted.seen_messages[0]
                if message.get("role") == "system"
            ]
            self.assertTrue(
                any(
                    TURN_DISCIPLINE_RULE in content
                    for content in system_contents
                ),
                "la règle « outils d'abord, réponse ensuite » doit figurer "
                "dans le prompt système du chat",
            )
        finally:
            self.db.delete_session(session_id)

    def test_system_prompt_rules_are_numbered_in_order(self):
        """Un harnais propre se lit dans l'ordre : consignes uniques, croissantes.

        Les patches successifs avaient produit des numéros dupliqués
        (trois « 11 », deux « 13 ») et une règle « 18 » placée avant
        « 15 » — le modèle devait deviner où finit une consigne. Certaines
        consignes sont conditionnelles (image jointe, grounding strict) :
        un trou dans la suite est donc légitime, pas un doublon ni un
        retour en arrière.
        """
        scripted = ScriptedChatClient([list(FINAL_TURN)])
        session_id, _events = self._run_chat(scripted)
        try:
            system = "\n".join(
                str(message.get("content") or "")
                for message in scripted.seen_messages[0]
                if message.get("role") == "system"
            )
            numbers = [
                int(value)
                for value in re.findall(r"(?m)^\s*(\d{1,2})\.\s+\S", system)
            ]
            self.assertTrue(numbers, "aucune consigne numérotée trouvée")
            self.assertEqual(numbers[0], 1, "la première consigne doit être 1.")
            self.assertEqual(
                numbers,
                sorted(set(numbers)),
                "les consignes du prompt système doivent être uniques et "
                "numérotées dans l'ordre croissant",
            )
        finally:
            self.db.delete_session(session_id)

    def test_follow_up_uses_thread_sources_and_is_not_replaced(self):
        """Régression : une relance sourcée dans le fil ne doit pas être effacée.

        Cas réel : après une réponse sourcée sur Claude Opus 5.5, la relance
        « tu peux me sortir ces performances par rapport à Fable 5.1 ? » a vu
        sa réponse remplacée par un refus (« Je n'ai pas pu vérifier… ») —
        parce que le harnais n'acceptait comme preuve que les pages lues
        pendant le tour courant, ignorant les sources déjà citées.
        """
        session = self.db.create_session(title="relance sourcée")
        self.db.add_message(
            session_id=session["id"],
            role="assistant",
            content="Claude Opus 5.5 est environ 40 % moins cher [1].",
            metadata={
                "web_results": [
                    {
                        "title": "Anthropic — Claude Opus 5.5",
                        "snippet": (
                            "Opus 5.5 coûte 40 % de moins et est 30 % plus "
                            "rapide que Opus 5."
                        ),
                        "url": "https://example.org/opus-5-5",
                        "number": 1,
                    }
                ]
            },
        )
        answer = (
            "Par rapport à Fable 5.1, il vise la parité de performance :\n"
            "*   **Coût** : environ 40 % moins cher.\n"
            "*   **Vitesse** : environ 30 % plus rapide."
        )
        scripted = ScriptedChatClient(
            [
                [
                    {"message": {"content": answer}},
                    {
                        "message": {"role": "assistant", "content": ""},
                        "done": True,
                        "done_reason": "stop",
                        "eval_count": 20,
                        "prompt_eval_count": 40,
                    },
                ]
            ]
        )
        with patch("chat.server.main.client", scripted):
            response = self.client.post(
                "/api/chat/stream",
                headers=self.headers,
                json={
                    "session_id": session["id"],
                    "model": "gemma-4-e4b",
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "tu peux me sortir ces performances par "
                                "rapport à Fable 5.1 ?"
                            ),
                        }
                    ],
                    "web_search_enabled": True,
                    "web_search_mode": "auto",
                },
            )
            self.assertEqual(response.status_code, 200)
            events = []
            for line in response.text.splitlines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    events.append(json.loads(line[6:]))
        try:
            replace = next(
                event
                for event in events
                if event.get("type") == "content_replace"
            )
            self.assertNotIn("Je n’ai pas pu vérifier", replace["text"])
            self.assertIn("parité de performance", replace["text"])
            self.assertIn("40 %", replace["text"])
            self.assertIn("30 %", replace["text"])
            messages = self.db.get_session_messages(session["id"])
            assistant = [
                item for item in messages if item["role"] == "assistant"
            ][-1]
            self.assertNotIn("Je n’ai pas pu vérifier", assistant["content"])
            self.assertIn("parité de performance", assistant["content"])
        finally:
            self.db.delete_session(session["id"])


if __name__ == "__main__":
    unittest.main()
