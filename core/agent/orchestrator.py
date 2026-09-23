"""Agent orchestrator — a deterministic state machine around the model.

The loop is the product: ``THINK → (tool calls → results) → … → FINAL``,
with hard guarantees that no run escapes its budget:

- bounded turns and bounded token budget per model call;
- ``finish_reason=length`` without a tool call ⇒ retry once with a
  doubled budget (the one real Gemma 4 failure mode measured in
  Phase 0: reasoning + call truncated by the budget);
- identical tool calls repeated ⇒ loop detected, divergence forced;
- tool errors are structured feedback the model can repair from;
- every observable step is an ``AgentEvent`` (streamed + persisted).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.agent import events as ev
from core.agent.tools import ToolRegistry, ToolResult
from core.agent.tools_web import pick_urls_for_reading

MAX_TOOL_BUDGET = 12_288
LOOP_SIGNATURE_REPEATS = 3


@dataclass
class AgentConfig:
    model: str
    max_turns: int = 8
    initial_tool_budget: int = 2_048
    temperature: float = 0.2
    think: Any = "low"
    system_prompt: str = ""
    max_parallel_tools: int = 3
    # Harness rule: after a web_research, the model MUST read at least one
    # page (web_read) before answering. Snippets alone are how stale
    # index results and training priors sneak into answers.
    require_fetch_after_search: bool = False
    # Harness rule: when the request (or the user explicitly) demands a
    # web search, answering without any search is bounced once.
    force_search_directive: bool = False


@dataclass
class AgentRunResult:
    final_text: str
    done_reason: str  # stop | length | max_turns | error | stopped
    turns: int
    log: ev.EventLog = field(default_factory=ev.EventLog)
    usage: Dict[str, int] = field(default_factory=dict)


class AgentOrchestrator:
    """Drives one agent run; safe to instantiate per request."""

    def __init__(
        self,
        client: Any,
        registry: ToolRegistry,
        config: AgentConfig,
    ):
        self.client = client
        self.registry = registry
        self.config = config

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _tool_call_signature(call: Dict[str, Any]) -> str:
        function = call.get("function") or {}
        return f"{function.get('name', '')}:{function.get('arguments', '')}"

    async def _stream_turn(
        self,
        messages: List[Dict[str, Any]],
        tools_payload: List[Dict[str, Any]],
        budget: int,
        emit: Callable[[str, Dict[str, Any]], Awaitable[None]],
    ) -> Dict[str, Any]:
        """One model call: returns content, assembled tool_calls, usage."""
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        assembled: Dict[int, Dict[str, Any]] = {}
        final_chunk: Dict[str, Any] = {}

        async for chunk in self.client.stream_chat(
            model=self.config.model,
            messages=messages,
            tools=tools_payload or None,
            temperature=self.config.temperature,
            num_predict=budget,
            think=self.config.think,
        ):
            if chunk.get("_error"):
                raise RuntimeError(
                    f"inférence interrompue: {chunk.get('_error')}"
                )
            message = chunk.get("message", {})
            thinking = message.get("thinking")
            if thinking:
                reasoning_parts.append(thinking)
                await emit(
                    ev.REASONING_DELTA, {"text": thinking}
                )
            delta = message.get("content")
            if delta:
                content_parts.append(delta)
                await emit(ev.CONTENT_DELTA, {"text": delta})
            for fragment in message.get("tool_calls") or []:
                index = int(fragment.get("index") or 0)
                slot = assembled.setdefault(
                    index,
                    {"id": fragment.get("id") or f"call_{index}", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if fragment.get("id"):
                    slot["id"] = fragment["id"]
                function = fragment.get("function") or {}
                if function.get("name"):
                    slot["function"]["name"] += function["name"]
                if function.get("arguments"):
                    slot["function"]["arguments"] += function["arguments"]
            if chunk.get("done"):
                final_chunk = chunk

        tool_calls = [assembled[i] for i in sorted(assembled)]
        return {
            "content": "".join(content_parts),
            "reasoning": "".join(reasoning_parts),
            "tool_calls": tool_calls,
            "done_reason": final_chunk.get("done_reason") or "stop",
            "usage": {
                "prompt_tokens": final_chunk.get("prompt_eval_count", 0),
                "output_tokens": final_chunk.get("eval_count", 0),
                # Temps de décodage réellement mesuré par le client (ns) :
                # seule base honnête pour un tok/s agrégé multi-tours.
                "eval_duration_ns": int(final_chunk.get("eval_duration") or 0),
                "prompt_eval_duration_ns": int(
                    final_chunk.get("prompt_eval_duration") or 0
                ),
            },
        }

    # ---------------------------------------------------------------- run

    async def run(
        self,
        user_messages: List[Dict[str, Any]],
        on_event: Optional[Callable[[ev.AgentEvent], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> AgentRunResult:
        log = ev.EventLog()

        async def emit(type: str, payload: Dict[str, Any]) -> None:
            event = log.add(type, **payload)
            if on_event is not None:
                on_event(event)

        messages: List[Dict[str, Any]] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        messages.extend(user_messages)

        tools_payload = self.registry.to_openai()
        signatures: Dict[str, int] = {}
        budget = self.config.initial_tool_budget
        length_retry_used = False
        search_fired = False
        fetch_fired = False
        fetch_nudge_used = False
        search_nudge_used = False
        last_search_output = ""
        final_text = ""
        done_reason = "max_turns"
        turns_used = 0

        try:
            for turn in range(1, self.config.max_turns + 1):
                if should_stop is not None and should_stop():
                    done_reason = "stopped"
                    await emit(ev.AGENT_ERROR, {"code": "stopped_by_user", "message": "Exécution interrompue par l'utilisateur."})
                    break
                turns_used = turn
                await emit(ev.TURN_START, {"turn": turn, "budget": budget})
                outcome = await self._stream_turn(
                    messages, tools_payload, budget, emit
                )
                await emit(
                    ev.TURN_END,
                    {"turn": turn, **outcome["usage"], "done_reason": outcome["done_reason"]},
                )

                tool_calls = outcome["tool_calls"]

                if not tool_calls:
                    final_text = outcome["content"]
                    if (
                        outcome["done_reason"] == "length"
                        and not length_retry_used
                        and budget < MAX_TOOL_BUDGET
                    ):
                        # Phase 0 rule: the answer (or its reasoning) was
                        # truncated by our own budget — give it room once.
                        length_retry_used = True
                        budget = min(budget * 2, MAX_TOOL_BUDGET)
                        await emit(
                            ev.TOOL_RESULT,
                            {
                                "note": "budget_retried",
                                "new_budget": budget,
                            },
                        )
                        continue
                    if (
                        self.config.require_fetch_after_search
                        and search_fired
                        and not fetch_fired
                        and not fetch_nudge_used
                        and final_text.strip()
                    ):
                        # Harness rule: the model answered from snippets
                        # without reading a single page. The orchestrator
                        # does the reading itself: top URLs of the last
                        # search are fetched here and their content is
                        # injected into the context. No model discretion.
                        fetch_nudge_used = True
                        final_text = ""
                        top_urls = pick_urls_for_reading(
                            last_search_output or "", max_urls=4
                        )
                        if top_urls and self.registry.get("web_read"):
                            fetch_result = await self.registry.execute(
                                "web_read",
                                json.dumps({"urls": top_urls}),
                            )
                            await emit(
                                ev.TOOL_CALL,
                                {
                                    "id": "auto_fetch",
                                    "name": "web_read",
                                    "arguments": json.dumps({"urls": top_urls}),
                                    "repeat": 1,
                                    "auto": True,
                                },
                            )
                            await emit(
                                ev.TOOL_RESULT,
                                {
                                    "id": "auto_fetch",
                                    "name": "web_read",
                                    "ok": fetch_result.ok,
                                    "output": fetch_result.output,
                                    "error": fetch_result.error,
                                    "error_code": fetch_result.error_code,
                                    "duration_ms": fetch_result.duration_ms,
                                },
                            )
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Système : tu avais répondu sans lire "
                                        "les pages — interdit. Voici le contenu "
                                        "des pages les plus pertinentes de ta "
                                        "recherche, récupéré automatiquement. "
                                        "Réponds maintenant UNIQUEMENT à partir "
                                        "de ce contenu. Si une page contredit "
                                        "ta mémoire, LA PAGE GAGNE (elle est "
                                        "plus récente que toi). Si aucune page "
                                        "ne répond à la question, relance "
                                        "web_research avec une requête plus "
                                        "précise (ex : « résultat final … »).\n\n"
                                        + fetch_result.output
                                    ),
                                }
                            )
                            continue
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Système : tu as lancé une recherche Web "
                                    "mais tu n'as lu AUCUNE page. Les extraits "
                                    "seuls ne suffisent pas (index périmés, "
                                    "articles ambigus). Utilise web_read sur "
                                    "au moins une URL des résultats, puis "
                                    "réponds en te basant sur ce que tu as lu. "
                                    "Si aucun résultat ne répond à la question, "
                                    "relance web_research avec une requête plus "
                                    "précise."
                                ),
                            }
                        )
                        await emit(
                            ev.TOOL_RESULT,
                            {"note": "fetch_required_before_answer"},
                        )
                        continue
                    if (
                        self.config.force_search_directive
                        and not search_fired
                        and not search_nudge_used
                        and final_text.strip()
                    ):
                        # Harness rule: the request demanded a web search
                        # but the model answered from training memory.
                        search_nudge_used = True
                        final_text = ""
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Système : cette demande exige une "
                                    "recherche Web et tu n'as appelé aucun "
                                    "outil. Ta mémoire d'entraînement peut "
                                    "être périmée ou fausse ici. Utilise "
                                    "web_research maintenant, puis web_read "
                                    "sur les résultats, avant de répondre."
                                ),
                            }
                        )
                        await emit(
                            ev.TOOL_RESULT,
                            {"note": "search_required_by_request"},
                        )
                        continue
                    done_reason = outcome["done_reason"]
                    break

                # Persist the assistant turn exactly as the model built it.
                messages.append(
                    {
                        "role": "assistant",
                        "content": outcome["content"] or "",
                        "tool_calls": tool_calls,
                    }
                )

                executable = tool_calls[: self.config.max_parallel_tools]
                results: List[tuple[Dict[str, Any], ToolResult]] = []
                for call in executable:
                    name = (call.get("function") or {}).get("name", "")
                    arguments = (call.get("function") or {}).get("arguments", "")
                    if name == "web_research":
                        search_fired = True
                    if name == "web_read":
                        fetch_fired = True
                    signature = self._tool_call_signature(call)
                    repeats = signatures.get(signature, 0) + 1
                    signatures[signature] = repeats

                    await emit(
                        ev.TOOL_CALL,
                        {
                            "id": call.get("id"),
                            "name": name,
                            "arguments": arguments,
                            "repeat": repeats,
                        },
                    )
                    if repeats >= LOOP_SIGNATURE_REPEATS:
                        result = ToolResult(
                            ok=False,
                            error=(
                                "loop detected: this exact call was already "
                                "made; change approach or answer now"
                            ),
                            error_code="loop",
                        )
                    else:
                        result = await self.registry.execute(name, arguments)
                    if name == "web_research" and result.ok:
                        last_search_output = result.output
                    await emit(
                        ev.TOOL_RESULT,
                        {
                            "id": call.get("id"),
                            "name": name,
                            "ok": result.ok,
                            "output": result.output,
                            "error": result.error,
                            "error_code": result.error_code,
                            "duration_ms": result.duration_ms,
                        },
                    )
                    results.append((call, result))

                for call, result in results:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "name": (call.get("function") or {}).get("name", ""),
                            "content": result.for_model(),
                        }
                    )
        except (RuntimeError, asyncio.CancelledError) as exc:
            done_reason = "error"
            await emit(
                ev.AGENT_ERROR,
                {"code": "orchestrator_error", "message": str(exc)},
            )

        await emit(ev.FINAL, {"content": final_text, "done_reason": done_reason})
        return AgentRunResult(
            final_text=final_text,
            done_reason=done_reason,
            turns=turns_used,
            log=log,
            usage=log.usage_totals(),
        )
