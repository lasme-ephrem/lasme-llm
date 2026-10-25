"""Routes projets, sessions et mémoire personnelle."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from chat.contracts.schemas import (
    BranchRequest,
    MemoryCreateRequest,
    MemorySettingsRequest,
    MemoryUpdateRequest,
    MessageEditRequest,
    MessageUpdateRequest,
    MissionCreateRequest,
    MissionUpdateRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SessionCreateRequest,
    SessionImportRequest,
    SessionUpdateRequest,
    validate_model_name,
)
from chat.server.deps import deps
from chat.server.services.background import _memory_update_locks, _personal_memory_lock
from chat.worker.loop import execute_agent_mission
from core.artifacts import export_session_conversation
from core.memory.database import DEFAULT_PROJECT_ID
from core.memory.personal import refresh_generated_memories

router = APIRouter()


# --- PROJECTS ---
@router.get("/api/projects")
async def get_projects():
    return {"projects": deps.db.list_projects()}


@router.post("/api/projects")
async def create_project(payload: ProjectCreateRequest):
    model = validate_model_name(payload.default_model)
    return {
        "project": deps.db.create_project(
            payload.name,
            description=payload.description,
            instructions=payload.instructions,
            default_model=model,
            memory_mode=payload.memory_mode,
            project_type=payload.project_type,
            tags=payload.tags,
            color=payload.color,
            favorite=payload.favorite,
        )
    }


@router.put("/api/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdateRequest):
    changes = payload.model_dump(exclude_none=True)
    if project_id == DEFAULT_PROJECT_ID:
        immutable_fields = set(changes) - {"memory_mode"}
        if immutable_fields:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Le projet principal est permanent. "
                    "Seul son espace mémoire peut être modifié."
                ),
            )
    if "default_model" in changes:
        changes["default_model"] = validate_model_name(changes["default_model"])
    project = deps.db.update_project(project_id, **changes)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project": project}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    if project_id == DEFAULT_PROJECT_ID:
        raise HTTPException(status_code=400, detail="The default project cannot be deleted.")
    if not deps.db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    if not deps.db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    await asyncio.to_thread(
        deps.project_file_store.remove_project_storage,
        project_id,
    )
    return {"status": "deleted"}


# --- SESSIONS ---
@router.get("/api/sessions")
async def get_sessions(project_id: Optional[str] = None):
    return {"sessions": deps.db.list_sessions(project_id)}


@router.post("/api/sessions")
async def create_session(payload: SessionCreateRequest):
    title = payload.title.strip() or "Nouvelle Conversation"
    model = validate_model_name(payload.model)
    if not deps.db.get_project(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    session = deps.db.create_session(
        title=title,
        model=model,
        project_id=payload.project_id,
    )
    return session


@router.get("/api/sessions/search")
async def search_sessions_workspace(
    q: str = "",
    project_id: Optional[str] = None,
    limit: int = 25,
):
    items = deps.db.search_workspace(q, project_id=project_id, limit=limit)
    sessions = [
        {**it, "id": it.get("session_id")}
        for it in items
        if it.get("type") == "session"
    ]
    messages = [it for it in items if it.get("type") == "message"]
    artifacts = [it for it in items if it.get("type") == "artifact"]
    return {
        "query": q,
        "results": items,
        "sessions": sessions,
        "messages": messages,
        "artifacts": artifacts,
    }


@router.get("/api/sessions/{session_id}/export")
async def export_session_endpoint(session_id: str, format: str = "html"):
    session = deps.db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    messages = deps.db.get_session_messages(session_id)
    try:
        payload, media_type, filename = export_session_conversation(
            session,
            messages,
            output_format=format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/api/sessions/import")
async def import_session_endpoint(payload: SessionImportRequest):
    try:
        session = deps.db.import_session_bundle(
            payload.bundle,
            project_id=payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    msgs = deps.db.get_session_messages(session["id"])
    return {
        "session": session,
        "imported_messages": len(msgs),
    }


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    session = deps.db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    messages = deps.db.get_session_messages(session_id)
    return {"session": session, "messages": messages}


@router.put("/api/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdateRequest):
    model = (
        validate_model_name(payload.model)
        if payload.model is not None
        else None
    )
    try:
        session = deps.db.update_session(
            session_id,
            title=payload.title,
            project_id=payload.project_id,
            model=model,
            pinned=payload.pinned,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"session": session}


@router.put("/api/messages/{message_id}")
async def update_message(message_id: str, payload: MessageUpdateRequest):
    try:
        message = deps.db.update_message(message_id, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")
    return {"message": message}


@router.post("/api/sessions/{session_id}/branch")
async def branch_session(session_id: str, payload: BranchRequest):
    model = validate_model_name(payload.model) if payload.model else None
    try:
        branch = deps.db.branch_session(
            session_id,
            payload.message_id,
            replacement_content=payload.content,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session": branch}


@router.post("/api/sessions/{session_id}/messages/{message_id}/edit")
async def edit_session_message(
    session_id: str,
    message_id: str,
    payload: MessageEditRequest,
):
    if not deps.db.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        result = deps.db.edit_message_and_truncate(
            session_id,
            message_id,
            payload.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Message not found.")
    return {"ok": True, "remaining": result["remaining"]}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    deps.rag_store.clear(session_id)
    _memory_update_locks.pop(session_id, None)
    deps.db.delete_session(session_id)
    return {"status": "deleted"}


# --- PERSONAL MEMORY ---
@router.get("/api/memory")
async def get_personal_memory():
    return {
        "settings": deps.db.get_memory_settings(),
        "memories": deps.db.list_personal_memories(),
    }


@router.put("/api/memory/settings")
async def update_personal_memory_settings(payload: MemorySettingsRequest):
    return {
        "settings": deps.db.update_memory_settings(
            enabled=payload.enabled,
            auto_save=payload.auto_save,
        )
    }


@router.post("/api/memory")
async def create_personal_memory(payload: MemoryCreateRequest):
    try:
        memory = deps.db.add_personal_memory(payload.content, source="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"memory": memory}


@router.put("/api/memory/{memory_id}")
async def update_personal_memory(
    memory_id: str,
    payload: MemoryUpdateRequest,
):
    try:
        memory = deps.db.update_personal_memory(
            memory_id,
            content=payload.content,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"memory": memory}


@router.delete("/api/memory/{memory_id}")
async def delete_personal_memory(memory_id: str):
    if not deps.db.delete_personal_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"status": "deleted"}


@router.post("/api/memory/refresh")
async def refresh_personal_memory():
    if _personal_memory_lock.locked():
        return {"status": "busy", "generated": 0}
    async with _personal_memory_lock:
        generated = await refresh_generated_memories(
            deps.db,
            deps.client,
            deps.settings.chat_model,
        )
    return {"status": "ok", "generated": generated}


# --- SCHEDULED AGENT MISSIONS ---
@router.get("/api/missions")
async def get_missions(project_id: Optional[str] = None):
    return {"missions": deps.db.list_missions(project_id=project_id)}


@router.post("/api/missions")
async def create_mission(payload: MissionCreateRequest):
    model = validate_model_name(payload.model)
    preset = (
        "hourly"
        if payload.interval_minutes <= 60
        else ("weekly" if payload.interval_minutes >= 10080 else "daily")
    )
    try:
        mission = deps.db.create_mission(
            title=payload.title,
            prompt=payload.prompt,
            project_id=payload.project_id,
            model=model,
            schedule_preset=preset,
            interval_minutes=payload.interval_minutes,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mission": mission}


@router.put("/api/missions/{mission_id}")
async def update_mission(mission_id: str, payload: MissionUpdateRequest):
    changes = payload.model_dump(exclude_none=True)
    changes.pop("schedule_label", None)
    if "model" in changes:
        changes["model"] = validate_model_name(changes["model"])
    try:
        mission = deps.db.update_mission(mission_id, **changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found.")
    return {"mission": mission}


@router.delete("/api/missions/{mission_id}")
async def delete_mission(mission_id: str):
    if not deps.db.delete_mission(mission_id):
        raise HTTPException(status_code=404, detail="Mission not found.")
    return {"status": "deleted"}


@router.post("/api/missions/{mission_id}/run")
async def run_mission_now(mission_id: str):
    if not deps.db.get_mission(mission_id):
        raise HTTPException(status_code=404, detail="Mission not found.")
    try:
        result = await execute_agent_mission(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result
