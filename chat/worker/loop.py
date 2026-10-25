"""Boucle de traitement des jobs de fond."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Awaitable, Callable, Dict

from core.config import settings
from chat.server.deps import deps
from chat.server.services.background import (
    async_generate_and_update_title,
    async_update_conversation_memory,
    async_update_personal_memory,
)
from chat.server.services.text import clean_model_text

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


async def execute_agent_mission(mission_id: str) -> Dict[str, Any]:
    """Exécute une mission planifiée d'agent et dépose un rapport dans le Canvas."""
    mission = deps.db.get_mission(mission_id)
    if not mission:
        raise ValueError(f"Mission introuvable : {mission_id}")

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()
    deps.db.update_mission(mission_id, last_status="running", last_error="")

    title = str(mission.get("title") or "Mission Agent").strip()
    prompt = str(mission.get("prompt") or "").strip()
    project_id = str(mission.get("project_id") or "default").strip() or "default"
    model = str(mission.get("model") or settings.chat_model).strip() or settings.chat_model

    report_md = ""
    try:
        if deps.client is not None:
            reply = await deps.client.chat(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Tu es un agent de veille et de briefing souverain. "
                            "Rédige un rapport structuré en Markdown (Points clés, "
                            "Analyse détaillée, Actions recommandées) répondant à "
                            "la mission confiée."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                num_ctx=4_096,
                think=False,
                num_predict=900,
            )
            report_md = clean_model_text(
                reply.get("message", {}).get("content", "")
            ).strip()
    except Exception as exc:
        logger.info("Exécution hors-ligne de la mission %s (%s)", mission_id, exc)

    if not report_md:
        date_str = now_dt.strftime("%Y-%m-%d %H:%M UTC")
        report_md = (
            f"# Rapport de mission : {title}\n\n"
            f"- **Exécution** : `{date_str}`\n"
            f"- **Cadence** : `{mission.get('schedule_label') or 'Manuel'}`\n"
            f"- **Modèle cible** : `{model}`\n\n"
            f"## Objectif de la mission\n\n"
            f"{prompt}\n\n"
            f"## Synthèse & points de suivi\n\n"
            f"1. **Collecte & périmètre** : Vérification des sources et du contexte projet (`{project_id}`).\n"
            f"2. **Observations prioritaires** : Ce rapport a été généré par le planificateur local pour préparer votre revue.\n"
            f"3. **Prochaines actions** : Ouvrez la session associée pour approfondir un point avec l'agent ou actualiser les sources Web/RAG."
        )

    session = deps.db.create_session(
        f"⏰ {title}",
        project_id=project_id,
    )
    artifact = deps.artifact_store.create(
        project_id=project_id,
        title=f"Veille · {title}",
        content=report_md,
        kind="research",
        language="markdown",
        session_id=session["id"],
    )
    deps.db.add_message(session["id"], "user", prompt)
    deps.db.add_message(
        session["id"],
        "assistant",
        report_md,
        metadata={
            "mission_id": mission_id,
            "artifact_id": artifact.get("id"),
            "model": model,
        },
    )

    interval_minutes = max(5, int(mission.get("interval_minutes") or 1440))
    next_run_at = (
        (now_dt + datetime.timedelta(minutes=interval_minutes)).isoformat()
        if mission.get("enabled")
        else None
    )
    updated_mission = deps.db.update_mission(
        mission_id,
        last_run_at=now_iso,
        last_status="success",
        last_artifact_id=artifact.get("id"),
        last_session_id=session["id"],
        last_error="",
        next_run_at=next_run_at,
    )
    return {
        "mission": updated_mission,
        "artifact": artifact,
        "session": session,
    }


async def _handle_agent_mission(payload: dict) -> None:
    mission_id = str(payload.get("mission_id") or "").strip()
    if not mission_id:
        return
    try:
        await execute_agent_mission(mission_id)
    except Exception as exc:
        deps.db.update_mission(
            mission_id,
            last_status="error",
            last_error=str(exc)[:400],
        )
        raise


HANDLERS: Dict[str, Callable[[dict], Awaitable[None]]] = {
    "title": _handle_title,
    "session_memory": _handle_session_memory,
    "personal_memory": _handle_personal_memory,
    "document_index": _handle_document_index,
    "agent_mission": _handle_agent_mission,
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
                try:
                    due_missions = await asyncio.to_thread(deps.db.claim_due_missions)
                    for mission in due_missions:
                        await asyncio.to_thread(
                            jobs.enqueue,
                            "agent_mission",
                            {"mission_id": mission["id"]},
                        )
                except Exception:
                    pass
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # jamais de mort silencieuse du worker
            logger.warning("worker loop : %s", exc)
            await asyncio.sleep(max(poll_seconds, 1.0))
