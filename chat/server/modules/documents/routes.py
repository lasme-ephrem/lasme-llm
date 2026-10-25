"""Routes documents : upload/indexation RAG, liste, compatibilité historique."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from chat.server.deps import deps
from chat.server.modules.documents.indexing import (
    _index_stored_project_file,
)
from core.files import canonical_mime_type

router = APIRouter()

_LEGACY_RAG_FILE_PREFIX = "legacy:"


def _legacy_rag_document_id(file_id: str) -> Optional[str]:
    value = (file_id or "").strip()
    if not value.startswith(_LEGACY_RAG_FILE_PREFIX):
        return None
    document_id = value[len(_LEGACY_RAG_FILE_PREFIX):].strip()
    return document_id or None


def _legacy_rag_file_record(document: Dict[str, Any]) -> Dict[str, Any]:
    filename = str(document.get("filename") or "Document historique")
    extension = Path(filename).suffix.lower()
    kind = {
        ".pdf": "pdf",
        ".md": "markdown",
        ".docx": "word",
        ".xlsx": "spreadsheet",
        ".pptx": "presentation",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webp": "image",
    }.get(extension, "text")
    synthetic_id = f"{_LEGACY_RAG_FILE_PREFIX}{document['id']}"
    return {
        "id": synthetic_id,
        "legacy_document_id": document["id"],
        "project_id": document.get("scope_id"),
        "filename": filename,
        "display_name": filename,
        "extension": extension,
        "mime_type": canonical_mime_type(extension),
        "kind": kind,
        "size_bytes": 0,
        "page_count": int(document.get("page_count") or 0),
        "chunk_count": int(document.get("chunk_count") or 0),
        "status": "ready",
        "error": "",
        "metadata": {
            "legacy_index": True,
            "notice": (
                "Index historique conservé. L'original n'est plus disponible; "
                "réimportez-le pour restaurer le téléchargement."
            ),
        },
        "preview_url": "",
        "download_url": "",
        "created_at": document.get("created_at"),
        "updated_at": document.get("created_at"),
    }


def _get_legacy_rag_file(
    file_id: str,
    *,
    project_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    document_id = _legacy_rag_document_id(file_id)
    if not document_id:
        return None
    document = deps.rag_store.get_document(document_id)
    if not document:
        return None
    linked_file_id = document.get("file_id")
    if linked_file_id and deps.project_file_store.get(str(linked_file_id)):
        return None
    if project_id and document.get("scope_id") != project_id:
        return None
    return _legacy_rag_file_record(document)


def _resolve_selected_rag_file_ids(
    file_ids: List[str],
    project_id: str,
) -> List[str]:
    resolved: List[str] = []
    for file_id in file_ids:
        record = deps.project_file_store.get(file_id)
        if (
            record
            and record.get("project_id") == project_id
            and record.get("status") == "ready"
        ):
            resolved.append(file_id)
            continue
        legacy = _get_legacy_rag_file(file_id, project_id=project_id)
        if legacy:
            resolved.append(legacy["legacy_document_id"])
    return list(dict.fromkeys(resolved))


@router.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    scope_id: str = Form(...),
    wait_for_index: bool = Form(False),
):
    project = deps.db.get_project(scope_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )
    content = await file.read(deps.settings.max_upload_bytes + 1)
    if len(content) > deps.settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                "Document exceeds the "
                f"{deps.settings.max_upload_bytes // (1024 * 1024)} MB limit."
            ),
        )
    filename = file.filename or "document"
    try:
        stored_file, duplicate = await asyncio.to_thread(
            deps.project_file_store.add,
            project_id=scope_id,
            filename=filename,
            content=content,
            mime_type=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if duplicate and stored_file.get("status") == "ready":
        return {
            "status": "duplicate",
            "file": stored_file,
            "filename": stored_file["display_name"],
        }
    if duplicate and stored_file.get("status") == "indexing":
        return {
            "status": "indexing",
            "file": stored_file,
            "filename": stored_file["display_name"],
        }

    stored_file = deps.project_file_store.update(
        stored_file["id"],
        status="indexing",
        error="",
        metadata={
            **(stored_file.get("metadata") or {}),
            "queued_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
        },
    ) or stored_file

    if wait_for_index:
        try:
            stored_file = await _index_stored_project_file(
                scope_id=scope_id,
                filename=filename,
                content=content,
                stored_file=stored_file,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "file": deps.project_file_store.get(stored_file["id"]),
                },
            ) from exc
        return {
            "status": "success",
            "file": stored_file,
            "filename": stored_file["display_name"],
        }

    deps.job_store.enqueue(
        "document_index",
        {
            "scope_id": scope_id,
            "filename": filename,
            "file_id": stored_file["id"],
            "stored_file": stored_file,
        },
    )
    return {
        "status": "accepted",
        "file": stored_file,
        "filename": stored_file["display_name"],
    }


@router.delete("/api/documents/clear")
async def clear_documents(scope_id: str):
    removed_from_index = deps.rag_store.clear(scope_id)
    removed_files = deps.project_file_store.clear_project(scope_id)
    return {
        "status": "cleared",
        "documents_removed": max(removed_from_index, removed_files),
        "files_removed": removed_files,
    }


@router.get("/api/documents")
async def list_documents(scope_id: str):
    files = deps.project_file_store.list(scope_id)
    visible_file_ids = {item["id"] for item in files}
    legacy_files = [
        _legacy_rag_file_record(document)
        for document in deps.rag_store.list_documents(scope_id)
        if (
            not document.get("file_id")
            or document.get("file_id") not in visible_file_ids
        )
    ]
    files = [*files, *legacy_files]
    return {"documents": files, "files": files}
