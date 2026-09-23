import asyncio
import unittest

from core.agent.builtin import build_default_registry
from core.agent.events import EventLog
from core.agent.orchestrator import AgentConfig, AgentOrchestrator
from core.agent.tools import (
    SCHEMA_VIOLATION,
    ToolDefinition,
    ToolRegistry,
    validate_arguments,
)


def tool_call_chunk(index, name="", arguments="", call_id=None):
    return {
        "message": {
            "tool_calls": [
                {
                    "index": index,
                    "id": call_id,
                    "function": {"name": name, "arguments": arguments},
                }
            ]
        }
    }


def content_chunk(text):
    return {"message": {"content": text}}


def reasoning_chunk(text):
    return {"message": {"thinking": text}}


def final_chunk(done_reason="stop", prompt=10, output=5):
    return {
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": done_reason,
        "eval_count": output,
        "prompt_eval_count": prompt,
    }


class ScriptedClient:
    """Replays prepared chunk lists, one per model call."""

    def __init__(self, turns: List[List[Dict[str, Any]]]):
        self.turns = list(turns)
        self.calls: List[Dict[str, Any]] = []

    async def stream_chat(self, *, model, messages, tools=None, **kwargs):
        self.calls.append(
            {
                "model": model,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "kwargs": kwargs,
            }
        )
        for chunk in self.turns.pop(0):
            yield chunk


class ValidateArgumentsTests(unittest.TestCase):
    def test_accepts_valid_and_rejects_missing_required(self):
        schema = {
            "type": "object",
            "properties": {"city": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["city"],
        }
        validate_arguments({"city": "Lyon", "days": 3}, schema)
        with self.assertRaises(ValueError):
            validate_arguments({"days": 3}, schema)

    def test_rejects_wrong_type_and_bad_enum(self):
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "unit": {"type": "string", "enum": ["C", "F"]},
            },
            "required": ["city"],
        }
        with self.assertRaises(ValueError):
            validate_arguments({"city": 42}, schema)
        with self.assertRaises(ValueError):
            validate_arguments({"city": "Lyon", "unit": "K"}, schema)


class ToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_happy_path_and_truncation(self):
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="shout",
                description="crie",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                handler=lambda args: asyncio.sleep(0, result=args["text"].upper()),
                max_output_chars=10,
            )
        )
        result = await registry.execute("shout", '{"text": "bonjour le monde"}')
        self.assertTrue(result.ok)
        self.assertTrue(result.meta["truncated"])
        self.assertIn("BONJOUR", result.output)
        self.assertIn("tronquée", result.output)

    async def test_execute_failure_modes(self):
        registry = build_default_registry()
        invalid_json = await registry.execute("calculate", "{pas du json")
        self.assertFalse(invalid_json.ok)
        self.assertEqual(invalid_json.error_code, "invalid_json")

        schema = await registry.execute("calculate", '{"expression": 42}')
        self.assertFalse(schema.ok)
        self.assertEqual(schema.error_code, SCHEMA_VIOLATION)

        unknown = await registry.execute("does_not_exist", "{}")
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.error_code, "unknown_tool")

        async def hang(args):
            await asyncio.sleep(10)

        registry.register(
            ToolDefinition(
                name="hang",
                description="bloque",
                parameters={"type": "object", "properties": {}},
                handler=hang,
                timeout_s=0.05,
            )
        )
        timeout = await registry.execute("hang", "{}")
        self.assertFalse(timeout.ok)
        self.assertEqual(timeout.error_code, "timeout")

    async def test_calculator_rejects_non_arithmetic(self):
        registry = build_default_registry()
        result = await registry.execute("calculate", '{"expression": "__import__(1)"}')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "execution_error")

    def test_registry_rejects_duplicates_and_bad_names(self):
        registry = build_default_registry()
        with self.assertRaises(ValueError):
            registry.register(build_default_registry()._tools["calculate"])
        with self.assertRaises(ValueError):
            ToolRegistry().register(
                ToolDefinition(
                    name="bad name!",
                    description="",
                    parameters={"type": "object"},
                    handler=None,
                )
            )


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def _config(self, **overrides):
        defaults = dict(model="gemma-4-12b", max_turns=4)
        defaults.update(overrides)
        return AgentConfig(**defaults)

    def _registry(self):
        return build_default_registry()

    async def test_direct_answer_without_tools(self):
        client = ScriptedClient(
            [
                [
                    reasoning_chunk("je reflechis"),
                    content_chunk("Il est "),
                    content_chunk("14h."),
                    final_chunk(),
                ]
            ]
        )
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run(
            [{"role": "user", "content": "quelle heure est-il ?"}]
        )
        self.assertEqual(result.final_text, "Il est 14h.")
        self.assertEqual(result.done_reason, "stop")
        self.assertEqual(result.turns, 1)
        types = [e.type for e in result.log.events]
        self.assertIn("turn_start", types)
        self.assertIn("reasoning_delta", types)
        self.assertIn("final", types)

    async def test_tool_round_trip(self):
        client = ScriptedClient(
            [
                [
                    tool_call_chunk(0, name="calculate", arguments='{"expr', call_id="c1"),
                    tool_call_chunk(0, arguments='ession": "(2+3)*4"}'),
                    final_chunk(done_reason="tool_calls"),
                ],
                [content_chunk("Le resultat est 20."), final_chunk()],
            ]
        )
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run(
            [{"role": "user", "content": "combien font (2+3)*4 ?"}]
        )
        self.assertEqual(result.final_text, "Le resultat est 20.")
        self.assertEqual(result.done_reason, "stop")
        self.assertEqual(result.turns, 2)
        tool_results = [
            e for e in result.log.events if e.type == "tool_result"
        ]
        self.assertTrue(tool_results[0].payload["ok"])
        self.assertEqual(tool_results[0].payload["output"], "20")
        # The conversation sent on turn 2 contains the tool exchange.
        second_call_messages = client.calls[1]["messages"]
        roles = [m["role"] for m in second_call_messages]
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)

    async def test_invalid_arguments_feed_structured_error_back(self):
        client = ScriptedClient(
            [
                [
                    tool_call_chunk(0, name="calculate", arguments='{"expression": 42}'),
                    final_chunk(done_reason="tool_calls"),
                ],
                [
                    tool_call_chunk(0, name="calculate", arguments='{"expression": "6*7"}'),
                    final_chunk(done_reason="tool_calls"),
                ],
                [content_chunk("La reponse est 42."), final_chunk()],
            ]
        )
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run([{"role": "user", "content": "6*7 ?"}])
        self.assertIn("42", result.final_text)
        tool_results = [
            e for e in result.log.events if e.type == "tool_result"
        ]
        self.assertFalse(tool_results[0].payload["ok"])
        self.assertEqual(tool_results[0].payload["error_code"], "schema_violation")
        # The model saw the structured error in the tool message.
        second_call_messages = client.calls[1]["messages"]
        tool_message = next(m for m in second_call_messages if m["role"] == "tool")
        self.assertIn("schema_violation", tool_message["content"])

    async def test_length_truncation_retries_with_doubled_budget(self):
        client = ScriptedClient(
            [
                [content_chunk("reponse cou"), final_chunk(done_reason="length", output=2048)],
                [content_chunk("reponse complete."), final_chunk()],
            ]
        )
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run([{"role": "user", "content": "long sujet"}])
        self.assertEqual(result.final_text, "reponse complete.")
        budgets = [c["kwargs"]["num_predict"] for c in client.calls]
        self.assertEqual(budgets, [2048, 4096])

    async def test_loop_detection_forces_divergence(self):
        same = '{"expression": "1+1"}'
        client = ScriptedClient(
            [
                [tool_call_chunk(0, name="calculate", arguments=same), final_chunk(done_reason="tool_calls")],
                [tool_call_chunk(0, name="calculate", arguments=same), final_chunk(done_reason="tool_calls")],
                [tool_call_chunk(0, name="calculate", arguments=same), final_chunk(done_reason="tool_calls")],
                [content_chunk("C'est 2."), final_chunk()],
            ]
        )
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run([{"role": "user", "content": "1+1 ?"}])
        self.assertEqual(result.final_text, "C'est 2.")
        calls = [e for e in result.log.events if e.type == "tool_call"]
        results = [e for e in result.log.events if e.type == "tool_result"]
        self.assertEqual(calls[-1].payload["repeat"], 3)
        self.assertFalse(results[-1].payload["ok"])
        self.assertEqual(results[-1].payload["error_code"], "loop")

    async def test_max_turns_is_bounded(self):
        turn = [tool_call_chunk(0, name="echo", arguments='{"text": "x"}'), final_chunk(done_reason="tool_calls")]
        client = ScriptedClient([list(turn) for _ in range(4)])
        orchestrator = AgentOrchestrator(
            client, self._registry(), self._config(max_turns=4)
        )
        result = await orchestrator.run([{"role": "user", "content": "boucle"}])
        self.assertEqual(result.done_reason, "max_turns")
        self.assertEqual(result.turns, 4)

    async def test_fetch_required_after_search_blocks_snippet_answers(self):
        # W-strict : web_search puis réponse directe = refus du harnais ;
        # le modèle est renvoyé lire une page avant de répondre.
        client = ScriptedClient(
            [
                [
                    tool_call_chunk(0, name="web_search", arguments='{"query": "vainqueur coupe du monde 2026"}'),
                    final_chunk(done_reason="tool_calls"),
                ],
                [content_chunk("L'Espagne a gagné (extrait)."), final_chunk()],
                [
                    tool_call_chunk(0, name="fetch_pages", arguments='{"urls": ["https://exemple.fr/a"]}'),
                    final_chunk(done_reason="tool_calls"),
                ],
                [content_chunk("L'Espagne a gagné, confirmé par la page lue."), final_chunk()],
            ]
        )
        registry = build_default_registry()
        registry.register(
            ToolDefinition(
                name="web_search",
                description="recherche",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                handler=lambda args: asyncio.sleep(0, result="[]"),
            )
        )
        orchestrator = AgentOrchestrator(
            client,
            registry,
            self._config(require_fetch_after_search=True),
        )
        result = await orchestrator.run(
            [{"role": "user", "content": "utilise le web"}]
        )
        self.assertIn("confirmé par la page lue", result.final_text)
        # La réponse basée sur les extraits seuls a été rejetée : le
        # premier contenu n'est pas le final.
        notes = [
            e for e in result.log.events
            if e.type == "tool_result" and e.payload.get("note")
        ]
        self.assertIn("fetch_required_before_answer", [n.payload["note"] for n in notes])
        # Le message de nudge a bien été injecté dans la conversation.
        third_call_messages = client.calls[2]["messages"]
        injected = [m for m in third_call_messages if m["role"] == "user" and "n'as lu AUCUNE page" in m["content"]]
        self.assertTrue(injected)

    async def test_fetch_rule_not_applied_without_search(self):
        client = ScriptedClient([[content_chunk("Réponse directe."), final_chunk()]])
        orchestrator = AgentOrchestrator(
            client,
            build_default_registry(),
            self._config(require_fetch_after_search=True),
        )
        result = await orchestrator.run([{"role": "user", "content": "bonjour"}])
        self.assertEqual(result.final_text, "Réponse directe.")
        self.assertEqual(result.done_reason, "stop")

    async def test_should_stop_interrupts(self):
        client = ScriptedClient([[content_chunk("x"), final_chunk()]])
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run(
            [{"role": "user", "content": "stop"}],
            should_stop=lambda: True,
        )
        self.assertEqual(result.done_reason, "stopped")
        self.assertEqual(result.turns, 0)

    async def test_inference_error_surfaces_as_agent_error(self):
        client = ScriptedClient([[{"_error": "ConnectError", "done": True}]])
        orchestrator = AgentOrchestrator(client, self._registry(), self._config())
        result = await orchestrator.run([{"role": "user", "content": "x"}])
        self.assertEqual(result.done_reason, "error")
        errors = [e for e in result.log.events if e.type == "agent_error"]
        self.assertTrue(errors)


class EventLogTests(unittest.TestCase):
    def test_sse_format_and_usage_totals(self):
        log = EventLog()
        log.add("turn_start", turn=1)
        log.add("tool_call", id="c1", name="echo", arguments="{}")
        log.add("turn_end", turn=1, prompt_tokens=30, output_tokens=12)
        log.add("turn_end", turn=2, prompt_tokens=60, output_tokens=8)
        log.add("final", content="ok", done_reason="stop")

        sse = log.events[-1].to_sse()
        self.assertTrue(sse.startswith("data: "))
        self.assertIn('"type": "final"', sse)
        self.assertTrue(sse.endswith("\n\n"))

        self.assertEqual(
            log.usage_totals(),
            {
                "prompt_tokens": 90,
                "output_tokens": 20,
                "eval_duration_ns": 0,
                "prompt_eval_duration_ns": 0,
            },
        )
        self.assertEqual(len(log.tool_calls()), 1)
        self.assertEqual(log.find_final(), "ok")


if __name__ == "__main__":
    unittest.main()
