"""Boucle de traitement des jobs de fond."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict

from chat.server.deps import deps
from chat.server.services.background import (
    async_generate_and_update_title,
    async_update_conversation_memory,
    async_update_personal_memory,
)

logger = logging.getLogger("lasme.worker")

Heartbeat = Callable[[], None]


async def _handle_title(payload: dict) -> None:
    await async_generate_and_update_title(
        str(payload.get("session_id") or ""),
        str(payload.get("prompt") or ""),
        str(payload.get("model") or ""),
    )


async def _handle_session_memory(payload: dict) -> None:
    await async_update_conversation_memory(
        str(payload.get("session_id") or ""),
        str(payload.get("model") or ""),
    )


async def _handle_personal_memory(payload: dict) -> None:
    await async_update_personal_memory(str(payload.get("model") or ""))


async def _handle_document_index(payload: dict) -> None:
    from chat.server.modules.documents.indexing import (
        _index_stored_project_file,
    )

    # Le contenu vit déjà dans la bibliothèque de fichiers : on le relit
    # au lieu de le stocker dans la file.
    file_id = str(payload.get("file_id") or "")
    content = deps.project_file_store.read(file_id)
    await _index_stored_project_file(
        scope_id=str(payload.get("scope_id") or ""),
        filename=str(payload.get("filename") or ""),
        content=content,
        stored_file=payload.get("stored_file") or {},
    )


HANDLERS: Dict[str, Callable[[dict], Awaitable[None]]] = {
    "title": _handle_title,
    "session_memory": _handle_session_memory,
    "personal_memory": _handle_personal_memory,
    "document_index": _handle_document_index,
}


async def process_one() -> bool:
    """Traite un job s'il y en a un ; True si un job a été traité."""
    jobs = deps.job_store
    job = await asyncio.to_thread(jobs.claim_next)
    if not job:
        return False
    handler = HANDLERS.get(str(job.get("kind") or ""))
    try:
        if handler is None:
            raise ValueError(f"Unknown job kind: {job.get('kind')}")
        await handler(job.get("payload") or {})
        await asyncio.to_thread(jobs.complete, job["id"])
    except Exception as exc:  # un job en échec ne casse jamais la boucle
        logger.warning("job %s en échec : %s", job.get("kind"), exc)
        await asyncio.to_thread(jobs.fail, job["id"], str(exc))
    return True


async def worker_loop(
    *,
    poll_seconds: float = 0.5,
    heartbeat: Heartbeat | None = None,
) -> None:
    """Boucle infinie : réserve, exécute, respire."""
    jobs = deps.job_store
    try:
        await asyncio.to_thread(jobs.requeue_stale_running)
    except Exception:
        pass
    while True:
        try:
            if heartbeat is not None:
                heartbeat()
            worked = await process_one()
            if not worked:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # jamais de mort silencieuse du worker
            logger.warning("worker loop : %s", exc)
            await asyncio.sleep(max(poll_seconds, 1.0))
