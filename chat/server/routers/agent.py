"""Agent endpoints: typed SSE runs, persisted missions, replay."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.agent.events import AgentEvent
from core.agent.orchestrator import AgentConfig, AgentOrchestrator
from core.agent.registry import build_agent_registry

AGENT_SYSTEM_PROMPT = (
    "Tu es Lasme, un assistant agentique local. Tu disposes d'outils : "
    "utilise-les quand ils apportent une réponse plus exacte ou plus "
    "fraîche que ta mémoire. Ta connaissance interne s'arrête à ta date "
    "de coupure d'entraînement : tout fait postérieur (événement, prix, "
    "version, actualité) doit être vérifié avec web_search puis "
    "fetch_pages avant d'être affirmé ; une page lue prime sur ta "
    "mémoire. Ne répète pas un appel d'outil identique. Quand tu "
    "réponds, sois net, structuré et honnête sur tes incertitudes. "
    "Cite les sources que tu as réellement lues."
)


@dataclass
class AgentDeps:
    """Everything the agent endpoints need, injected by main.py."""

    client: Any                    # LasmeLLMClient
    db: Any                        # DatabaseManager
    python_runner: Any
    rag_store: Any
    file_store: Any
    artifact_store: Any
    search_fn: Any                 # search_web_detailed
    fetch_fn: Any                  # fetch_url_content
    vision_model: str
    default_project_id: str
    validate_model: Any            # callable(str) -> str (raises HTTPException)
    default_temperature: float = 0.5


class AgentMessage(BaseModel):
    role: str = "user"
    content: str = Field(default="", max_length=100_000)


class AgentStreamRequest(BaseModel):
    messages: List[AgentMessage] = Field(min_length=1, max_length=40)
    model: Optional[str] = None
    max_turns: int = Field(default=8, ge=1, le=16)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    image_base64: Optional[str] = Field(default=None, max_length=8_000_000)
    project_id: Optional[str] = Field(default=None, max_length=64)


def create_agent_router(deps: AgentDeps) -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"])

    @router.post("/stream")
    async def agent_stream(req: AgentStreamRequest):
        """Agentic run with typed SSE events: reasoning, tools, results."""
        selected_model = deps.validate_model(req.model)

        async def rag_search(query: str, top_k: int):
            return deps.rag_store.search_scopes(
                [req.project_id or deps.default_project_id],
                query,
                top_k=top_k,
            )

        registry = build_agent_registry(
            search_fn=deps.search_fn,
            fetch_fn=deps.fetch_fn,
            rag_search_fn=rag_search,
            python_runner=deps.python_runner,
            file_store=deps.file_store,
            vision_client=deps.client,
            vision_model=deps.vision_model,
            prebound_image=(req.image_base64 or None),
            artifact_store=deps.artifact_store,
            default_project_id=req.project_id or deps.default_project_id,
        )

        system_prompt = AGENT_SYSTEM_PROMPT
        project = deps.db.get_project(req.project_id or deps.default_project_id)
        if project and (project.get("instructions") or "").strip():
            system_prompt += (
                "\n\nInstructions du projet : "
                + project["instructions"].strip()[:4_000]
            )
        if req.image_base64:
            system_prompt += (
                " Une image est jointe à cette mission : utilise l'outil "
                "analyze_image avec ta question pour l'examiner."
            )

        config = AgentConfig(
            model=selected_model,
            system_prompt=system_prompt,
            max_turns=req.max_turns,
            temperature=(
                deps.default_temperature
                if req.temperature is None
                else req.temperature
            ),
        )
        orchestrator = AgentOrchestrator(deps.client, registry, config)
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: AgentEvent) -> None:
            queue.put_nowait(event)

        async def run_agent() -> None:
            try:
                result = await orchestrator.run(
                    [
                        {"role": m.role, "content": m.content}
                        for m in req.messages
                    ],
                    on_event=on_event,
                )
                try:
                    deps.db.save_agent_run(
                        model=selected_model,
                        prompt=req.messages[-1].content if req.messages else "",
                        final_text=result.final_text,
                        done_reason=result.done_reason,
                        turns=result.turns,
                        events=result.log.to_list(),
                        usage=result.usage,
                    )
                except Exception:  # persistence must never break the stream
                    pass
            except Exception as exc:  # never leave the queue waiting
                on_event(
                    AgentEvent(
                        type="agent_error",
                        payload={
                            "code": "server_error",
                            "message": f"{type(exc).__name__}: {exc}",
                        },
                    )
                )
            finally:
                queue.put_nowait(None)

        async def event_stream():
            task = asyncio.create_task(run_agent())
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield event.to_sse()
            finally:
                if not task.done():
                    task.cancel()
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/runs")
    async def list_agent_runs(limit: int = 30):
        return {"runs": deps.db.list_agent_runs(min(limit, 100))}

    @router.get("/runs/{run_id}")
    async def get_agent_run(run_id: str):
        run = deps.db.get_agent_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run introuvable.")
        return run

    @router.delete("/runs/{run_id}")
    async def delete_agent_run(run_id: str):
        if not deps.db.delete_agent_run(run_id):
            raise HTTPException(status_code=404, detail="Run introuvable.")
        return {"ok": True}

    return router
