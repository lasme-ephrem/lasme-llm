"""API IDE de coding : arborescence, fichiers, sous-agents, terminal, agent."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from chat.contracts.schemas import (
    AgentRunRequest,
    FileSaveRequest,
    TerminalExecuteRequest,
    validate_model_name,
)
from chat.server.deps import deps
from coding.agent import LasmeCodingAgent
from coding.subagents.manager import subagent_manager
from core.security import resolve_workspace_path

router = APIRouter()


@router.get("/api/coding/tree")
async def get_coding_tree(path: str = ".", max_depth: int = 4):
    try:
        target_path = resolve_workspace_path(path or ".")
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Directory not found")

        tree_items = []
        for p in target_path.iterdir():
            if p.name.startswith(".") or p.name in ["__pycache__", "node_modules", "venv", ".git"]:
                continue
            tree_items.append({
                "name": p.name,
                "type": "directory" if p.is_dir() else "file",
                "path": str(p)
            })
        tree_items.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
        return {"path": str(target_path), "tree": tree_items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/coding/file")
async def get_coding_file(path: str = None, file: str = None):
    try:
        target = path or file or "README.md"
        file_path = resolve_workspace_path(target)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {"path": str(file_path), "name": file_path.name, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/coding/file")
async def save_coding_file(req: FileSaveRequest):
    try:
        target = req.path or getattr(req, 'file', None)
        if not target:
            raise HTTPException(status_code=400, detail="Missing file path")
        file_path = resolve_workspace_path(target)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(req.content, encoding="utf-8")
        return {"status": "success", "message": f"Saved {file_path.name}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/coding/subagents")
async def get_coding_subagents():
    return {"subagents": subagent_manager.list_subagents()}


@router.post("/api/coding/terminal")
async def run_coding_terminal(req: TerminalExecuteRequest):
    if not deps.settings.agent_terminal_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "The host terminal is disabled. "
                "Use the isolated Python runner."
            ),
        )
    from coding.tools.terminal_tools import tool_run_command
    result = await asyncio.to_thread(tool_run_command, req.command)
    return {"command": req.command, "output": result}


@router.post("/api/coding/agent/stream")
async def run_coding_agent_stream(req: AgentRunRequest):
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt empty")

    agent = LasmeCodingAgent(
        model_name=validate_model_name(req.model or deps.settings.coding_model)
    )

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def stream_callback(event_type: str, message: str, meta: dict = None):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                json.dumps({"type": event_type, "message": message, "meta": meta or {}})
            )

        async def task_runner():
            try:
                final_res = await agent.execute_task(prompt, callback=stream_callback)
                await queue.put(json.dumps({"type": "final", "message": final_res}))
            except Exception as e:
                await queue.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
                await queue.put("[DONE]")

        asyncio.create_task(task_runner())

        while True:
            item = await queue.get()
            if item == "[DONE]":
                yield "data: [DONE]\n\n"
                break
            yield f"data: {item}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
