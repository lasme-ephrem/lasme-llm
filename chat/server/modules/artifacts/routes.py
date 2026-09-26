"""Canvas versionnés (artefacts) : CRUD, aperçus isolés, exports."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from chat.contracts.schemas import (
    ArtifactCreateRequest,
    ArtifactPreviewRequest,
    ArtifactUpdateRequest,
)
from chat.server.deps import deps
from core.artifacts import EXPORT_FORMATS, export_artifact as build_artifact_export

router = APIRouter()

_artifact_preview_cache: Dict[str, Tuple[float, str]] = {}
_ARTIFACT_PREVIEW_TTL_SECONDS = 15 * 60
_ARTIFACT_PREVIEW_CACHE_LIMIT = 64


def _prune_artifact_previews(now: Optional[float] = None) -> None:
    current = time.monotonic() if now is None else now
    expired = [
        token
        for token, (expires_at, _) in _artifact_preview_cache.items()
        if expires_at <= current
    ]
    for token in expired:
        _artifact_preview_cache.pop(token, None)
    while len(_artifact_preview_cache) >= _ARTIFACT_PREVIEW_CACHE_LIMIT:
        oldest = min(
            _artifact_preview_cache,
            key=lambda item: _artifact_preview_cache[item][0],
        )
        _artifact_preview_cache.pop(oldest, None)


@router.get("/api/artifacts")
async def list_artifacts(project_id: str = "default"):
    return {"artifacts": deps.artifact_store.list(project_id)}


@router.post("/api/artifact-previews")
async def create_artifact_preview(payload: ArtifactPreviewRequest):
    """Create a short-lived isolated URL for an unsaved HTML Canvas."""
    now = time.monotonic()
    _prune_artifact_previews(now)
    token = secrets.token_urlsafe(24)
    _artifact_preview_cache[token] = (
        now + _ARTIFACT_PREVIEW_TTL_SECONDS,
        payload.content,
    )
    return {
        "url": f"/api/artifact-previews/{token}",
        "expires_in": _ARTIFACT_PREVIEW_TTL_SECONDS,
    }


@router.get("/api/artifact-previews/{token}")
async def get_artifact_preview(token: str):
    """Serve a Canvas in a sandbox with no application or network access."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token):
        raise HTTPException(status_code=404, detail="Preview not found.")
    now = time.monotonic()
    _prune_artifact_previews(now)
    cached = _artifact_preview_cache.get(token)
    if not cached or cached[0] <= now:
        _artifact_preview_cache.pop(token, None)
        raise HTTPException(status_code=404, detail="Preview expired or not found.")
    return Response(
        content=cached[1].encode("utf-8"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; "
                "img-src data: blob:; "
                "font-src data:; "
                "style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; "
                "connect-src 'none'; "
                "media-src data: blob:; "
                "frame-src 'none'; "
                "worker-src 'none'; "
                "object-src 'none'; "
                "form-action 'none'; "
                "base-uri 'none'"
            ),
            "Permissions-Policy": (
                "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
            ),
        },
    )


@router.post("/api/artifacts")
async def create_artifact(payload: ArtifactCreateRequest):
    if not deps.db.get_project(payload.project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    artifact = deps.artifact_store.create(**payload.model_dump())
    return {"artifact": artifact}


@router.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    artifact = deps.artifact_store.get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return {"artifact": artifact}


@router.put("/api/artifacts/{artifact_id}")
async def update_artifact(artifact_id: str, payload: ArtifactUpdateRequest):
    artifact = deps.artifact_store.add_version(
        artifact_id,
        payload.content,
        title=payload.title,
        change_summary=payload.change_summary,
        kind=payload.kind,
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return {"artifact": artifact}


@router.delete("/api/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str):
    if not deps.artifact_store.delete(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return {"status": "deleted"}


@router.get("/api/artifacts/{artifact_id}/export")
async def export_artifact(
    artifact_id: str,
    version: Optional[int] = None,
    format: Optional[str] = None,
):
    artifact = deps.artifact_store.get(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    selected = artifact.get("content", "")
    if version is not None:
        selected_version = next(
            (
                item
                for item in artifact.get("versions", [])
                if int(item["version_number"]) == version
            ),
            None,
        )
        if not selected_version:
            raise HTTPException(status_code=404, detail="Artifact version not found.")
        selected = selected_version["content"]
    default_format = {
        "code": "txt",
        "markdown": "md",
        "research": "md",
        "table": "csv",
        "html": "html",
        "interactive": "html",
        "diagram": "svg",
        "presentation": "pptx",
    }.get(artifact.get("kind"), "md")
    output_format = (format or default_format).lower().strip()
    if output_format not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported export format.")
    try:
        payload, media_type, filename = await asyncio.to_thread(
            build_artifact_export,
            artifact["title"],
            selected,
            kind=artifact.get("kind") or "document",
            output_format=output_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
