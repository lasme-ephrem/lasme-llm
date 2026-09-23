"""Agent de coding : contrat de callback, confinement fs, listes blanches.

Couvre les garanties de `coding/` : le callback à 3 arguments réellement
envoyés par `LasmeCodingAgent.execute_task`, le refus d'évasion du workspace
par les outils fs, la liste blanche d'outils des sous-agents (schéma ET
exécution) et l'absence d'outils destructifs / terminal par défaut.
"""

import asyncio
import json
import unittest

from coding.agent import LasmeCodingAgent
from coding.cli import agent_callback
from coding.subagents.manager import SubagentInstance
from coding.tools.fs_tools import tool_view_file, tool_write_file
from core.config import settings


class ScriptedCodingClient:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"message": self.turns.pop(0)}


class CodingAgentCallbackTests(unittest.TestCase):
    def test_agent_callback_accepts_the_three_argument_contract(self):
        # coding/agent.py appelle callback(type, payload, meta) : avant la
        # correction, le callback de la CLI n'en acceptait que deux et le
        # premier événement levait un TypeError.
        for event_type, payload in (
            ("status", "Step 1/20: Reasoning..."),
            ("thought", "Je regarde l'arborescence."),
            ("tool_call", "Invoking tool `list_dir`"),
            ("tool_result", "Result from `list_dir`"),
        ):
            agent_callback(event_type, payload, {"step": 1})
        # Deux arguments restent acceptés (meta facultatif).
        agent_callback("status", "sans meta")

    def test_execute_task_streams_events_with_meta_and_returns_final(self):
        agent = LasmeCodingAgent(model_name="gemma-4-e4b")
        agent.client = ScriptedCodingClient(
            [
                {
                    "content": "Je consulte le dépôt.",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "list_dir",
                                "arguments": {"path": "."},
                            }
                        }
                    ],
                },
                {"content": "Tâche terminée."},
            ]
        )
        events = []

        def callback(event_type, payload, meta):
            events.append((event_type, payload, meta))

        result = asyncio.run(
            agent.execute_task("Regarde le dépôt", callback=callback)
        )
        self.assertEqual(result, "Tâche terminée.")
        types = [event[0] for event in events]
        self.assertIn("thought", types)
        self.assertIn("tool_call", types)
        self.assertIn("tool_result", types)
        # Tout événement porte bien le meta (3e argument).
        self.assertTrue(all(isinstance(event[2], dict) for event in events))


class CodingFsToolsTests(unittest.TestCase):
    def test_fs_tools_refuse_workspace_escapes(self):
        for result in (
            tool_view_file("../outside.txt"),
            tool_write_file("../escape.txt", "pirate"),
            tool_view_file("C:\\Windows\\win.ini"),
        ):
            self.assertTrue(
                result.startswith("Error"),
                f"évasion non refusée : {result!r}",
            )

    def test_destructive_and_terminal_tools_disabled_by_default(self):
        previous = (
            settings.allow_destructive_agent_tools,
            settings.agent_terminal_enabled,
        )
        settings.allow_destructive_agent_tools = False
        settings.agent_terminal_enabled = False
        try:
            agent = LasmeCodingAgent(model_name="gemma-4-e4b")
            names = {schema["function"]["name"] for schema in agent.tools_schema}
            self.assertNotIn("delete_file", names)
            self.assertNotIn("move_file", names)
            self.assertNotIn("run_command", names)
            self.assertNotIn("delete_file", agent.tools_map)
            self.assertNotIn("run_command", agent.tools_map)
        finally:
            (
                settings.allow_destructive_agent_tools,
                settings.agent_terminal_enabled,
            ) = previous


class SubagentRoleTests(unittest.TestCase):
    def test_researcher_cannot_use_write_tools(self):
        instance = SubagentInstance(
            "sub_test", "researcher", "Explore le dépôt", model_name="gemma-4-e4b"
        )
        scripted = ScriptedCodingClient(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": {
                                    "path": "pirate.txt",
                                    "content": "hacked",
                                },
                            }
                        }
                    ],
                },
                {"content": "Rapport."},
            ]
        )
        instance.client = scripted
        writes = []

        def fake_write_file(path, content):
            writes.append(path)
            return "wrote"

        tools_schema = [
            {"type": "function", "function": {"name": "write_file", "parameters": {}}},
            {"type": "function", "function": {"name": "view_file", "parameters": {}}},
        ]
        tools_map = {
            "write_file": fake_write_file,
            "view_file": lambda path: "ok",
        }

        result = asyncio.run(instance.run(tools_schema, tools_map))
        self.assertEqual(result, "Rapport.")
        self.assertEqual(instance.status, "completed")
        # La liste blanche est appliquée à l'exécution, pas seulement au
        # schéma : l'outil interdit n'a jamais tourné.
        self.assertEqual(writes, [])
        first_tools = {
            schema["function"]["name"]
            for schema in (scripted.calls[0].get("tools") or [])
        }
        self.assertNotIn("write_file", first_tools)
        self.assertIn("view_file", first_tools)
        # Et le refus est renvoyé au modèle comme sortie d'outil.
        transcript = json.dumps(
            [call.get("messages") for call in scripted.calls],
            ensure_ascii=False,
        )
        self.assertIn("not allowed", transcript)


if __name__ == "__main__":
    unittest.main()
