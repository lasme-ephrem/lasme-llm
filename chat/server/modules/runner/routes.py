"""Runner Python sandboxé (Docker sans réseau) : statut, exécution, fichiers."""

from __future__ import annotations

import asyncio
import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from chat.contracts.schemas import PythonRunRequest
from chat.server.deps import deps
from core.security import is_direct_local_request

router = APIRouter()


@router.get("/api/runner/status")
async def get_python_runner_status():
    return {
        "available": await deps.python_runner.available(),
        "engine": "docker",
        "network": "disabled",
        "max_seconds": 20,
    }


@router.post("/api/runner/python")
async def run_python(payload: PythonRunRequest, request: Request):
    if (
        not is_direct_local_request(request)
        and not deps.settings.allow_remote_coding
    ):
        raise HTTPException(
            status_code=403,
            detail="The Python runner is local-only.",
        )
    try:
        await asyncio.to_thread(deps.python_runner.cleanup)
        result = await deps.python_runner.run(
            payload.code,
            timeout_seconds=payload.timeout_seconds,
            inputs=payload.inputs,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"result": result.model_dump()}


@router.get("/api/runner/jobs/{job_id}/files/{filename}")
async def download_runner_file(job_id: str, filename: str, request: Request):
    if (
        not is_direct_local_request(request)
        and not deps.settings.allow_remote_coding
    ):
        raise HTTPException(
            status_code=403,
            detail="Runner outputs are local-only.",
        )
    path = deps.python_runner.output_path(job_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="Runner output not found.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)
