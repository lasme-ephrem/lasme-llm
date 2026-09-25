"""Bibliothèque de fichiers projet : métadonnées, aperçus, téléchargements."""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Dict
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from chat.contracts.schemas import ProjectFileUpdateRequest
from chat.server.deps import deps
from chat.server.modules.documents.indexing import (
    _index_project_image,
    _index_project_pdf,
)
from chat.server.modules.documents.routes import (
    _get_legacy_rag_file,
    _legacy_rag_file_record,
)
from core.files import canonical_mime_type

router = APIRouter()


def _content_disposition(filename: str, *, inline: bool) -> str:
    fallback = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename) or "document"
    encoded = quote(filename, safe="")
    mode = "inline" if inline else "attachment"
    return f"{mode}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _project_file_response_headers(
    filename: str,
    *,
    inline: bool,
) -> Dict[str, str]:
    return {
        "Content-Disposition": _content_disposition(
            filename,
            inline=inline,
        ),
        "Cache-Control": "private, max-age=300" if inline else "no-store",
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": (
            "sandbox; default-src 'none'; frame-ancestors 'self';"
        ),
    }


@router.get("/api/files/{file_id}")
async def get_project_file(file_id: str):
    legacy = _get_legacy_rag_file(file_id)
    if legacy:
        return {"file": legacy}
    record = deps.project_file_store.get(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")
    return {"file": record}


@router.put("/api/files/{file_id}")
async def update_project_file(
    file_id: str,
    payload: ProjectFileUpdateRequest,
):
    legacy = _get_legacy_rag_file(file_id)
    if legacy:
        if not payload.display_name:
            return {"file": legacy}
        try:
            renamed = deps.rag_store.rename_document(
                legacy["legacy_document_id"],
                payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not renamed:
            raise HTTPException(status_code=404, detail="File not found.")
        document = deps.rag_store.get_document(legacy["legacy_document_id"])
        return {"file": _legacy_rag_file_record(document or {})}
    try:
        record = deps.project_file_store.update(
            file_id,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")
    if payload.display_name:
        deps.rag_store.rename_document(file_id, record["display_name"])
    return {"file": record}


@router.post("/api/files/{file_id}/reindex")
async def reindex_project_file(file_id: str):
    record = deps.project_file_store.get(file_id)
    if not record:
        if _get_legacy_rag_file(file_id):
            raise HTTPException(
                status_code=409,
                detail="Re-import the original file to rebuild a legacy index.",
            )
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        content = deps.project_file_store.read(file_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410,
            detail="The stored original is missing.",
        ) from exc
    deps.project_file_store.update(file_id, status="indexing", error="")
    try:
        if record["kind"] == "image" and deps.settings.vision_model:
            chunks, metadata = await _index_project_image(
                scope_id=record["project_id"],
                filename=record["filename"],
                content=content,
                file_id=file_id,
                mime_type=record["mime_type"],
            )
        elif record["kind"] == "pdf":
            chunks, metadata = await _index_project_pdf(
                scope_id=record["project_id"],
                filename=record["filename"],
                content=content,
                file_id=file_id,
                mime_type=record["mime_type"],
            )
        else:
            chunks = await asyncio.to_thread(
                deps.rag_store.add_document,
                record["project_id"],
                record["filename"],
                content,
                file_id=file_id,
                mime_type=record["mime_type"],
            )
            metadata = {"indexer": "document_parser"}
        indexed = next(
            (
                item
                for item in deps.rag_store.list_documents(record["project_id"])
                if item.get("file_id") == file_id
            ),
            {},
        )
        updated = deps.project_file_store.update(
            file_id,
            status="ready",
            page_count=int(indexed.get("page_count") or 0),
            chunk_count=chunks,
            error="",
            metadata={
                "indexed_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
                **metadata,
            },
        )
        return {"status": "ready", "file": updated, "chunks": chunks}
    except Exception as exc:
        deps.project_file_store.update(
            file_id,
            status="error",
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/files/{file_id}/content")
async def preview_project_file(file_id: str):
    legacy = _get_legacy_rag_file(file_id)
    if legacy:
        sections = deps.rag_store.preview_indexed_document(
            legacy["legacy_document_id"],
        )
        text = "\n\n".join(section["text"] for section in sections)
        return Response(
            content=text,
            media_type="text/plain",
            headers=_project_file_response_headers(
                legacy["display_name"],
                inline=True,
            ),
        )
    record = deps.project_file_store.get(file_id)
    path = deps.project_file_store.path_for(file_id)
    if not record or not path:
        raise HTTPException(status_code=404, detail="File not found.")
    inline = record["kind"] in {"pdf", "image"}
    return FileResponse(
        path,
        media_type=canonical_mime_type(record["extension"]),
        headers=_project_file_response_headers(
            record["display_name"],
            inline=inline,
        ),
    )


@router.get("/api/files/{file_id}/download")
async def download_project_file(file_id: str):
    if _get_legacy_rag_file(file_id):
        raise HTTPException(
            status_code=410,
            detail=(
                "The original file is unavailable for this historical index. "
                "Re-import the document to restore downloads."
            ),
        )
    record = deps.project_file_store.get(file_id)
    path = deps.project_file_store.path_for(file_id)
    if not record or not path:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path,
        media_type=canonical_mime_type(record["extension"]),
        headers=_project_file_response_headers(
            record["display_name"],
            inline=False,
        ),
    )


@router.get("/api/files/{file_id}/preview")
async def get_project_file_preview(file_id: str):
    legacy = _get_legacy_rag_file(file_id)
    if legacy:
        return {
            "mode": "sections",
            "file": legacy,
            "sections": deps.rag_store.preview_indexed_document(
                legacy["legacy_document_id"],
            ),
        }
    record = deps.project_file_store.get(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")
    if record["kind"] in {"pdf", "image"}:
        return {
            "mode": record["kind"],
            "file": record,
            "url": record["preview_url"],
        }
    try:
        sections = await asyncio.to_thread(
            deps.rag_store.preview,
            record["filename"],
            deps.project_file_store.read(file_id),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "mode": "structured",
        "file": record,
        "sections": sections,
    }


@router.delete("/api/files/{file_id}")
async def delete_project_file(file_id: str):
    legacy = _get_legacy_rag_file(file_id)
    if legacy:
        deps.rag_store.delete_document(legacy["legacy_document_id"])
        return {"status": "deleted", "legacy": True}
    record = deps.project_file_store.get(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")
    deps.rag_store.delete_document(file_id)
    deps.project_file_store.delete(file_id)
    return {"status": "deleted", "file_id": file_id}
