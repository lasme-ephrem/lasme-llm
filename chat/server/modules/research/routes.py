"""Recherche approfondie (deep research) : plan multi-étapes + synthèse SSE."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from chat.contracts.schemas import DeepResearchRequest, validate_model_name
from chat.server.deps import deps
from chat.server.modules.documents.routes import _resolve_selected_rag_file_ids
from chat.server.services.text import clean_model_text, compact_web_source_metadata
from core.inference.profiles import get_model_profile
from core.mcp.format import format_search_results
from core.mcp.pool import get_mcp_client
from core.mcp.research import research_report
from core.research import build_research_plan, merge_research_results

router = APIRouter()


@router.post("/api/research/stream")
async def deep_research_stream(req: DeepResearchRequest):
    selected_model = validate_model_name(req.model or deps.settings.reasoning_model)
    project = deps.db.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if req.temporary and req.session_id:
        raise HTTPException(
            status_code=400,
            detail="A temporary conversation cannot use a saved session.",
        )
    session_id = req.session_id
    is_new_session = False
    if session_id:
        session = deps.db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session.get("project_id") != req.project_id:
            raise HTTPException(
                status_code=409,
                detail="The session does not belong to the selected project.",
            )
    elif not req.temporary:
        is_new_session = True
        session = deps.db.create_session(
            title=req.question[:80],
            model=selected_model,
            project_id=req.project_id,
        )
        session_id = session["id"]
    user_message_id = (
        deps.db.add_message(
            session_id,
            "user",
            req.question,
            metadata={"mode": "deep_research"},
        )
        if session_id
        else None
    )

    async def research_events():
        plan = build_research_plan(req.question)
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'project_id': req.project_id, 'user_message_id': user_message_id, 'research_mode': True, 'temporary': req.temporary})}\n\n"
        yield f"data: {json.dumps({'type': 'research_plan', 'steps': plan})}\n\n"
        reports: List[Dict[str, Any]] = []
        provider_notes: List[str] = []
        for index, step in enumerate(plan):
            yield f"data: {json.dumps({'type': 'research_step', 'step_id': step['id'], 'index': index, 'status': 'running', 'label': step['label'], 'query': step['query']})}\n\n"
            report = await research_report(
                get_mcp_client(), step["query"]
            )
            reports.append(report)
            provider_answer = str(report.get("provider_answer") or "").strip()
            if provider_answer:
                provider_answer = re.sub(
                    r"\[(?:\d+\s*(?:,\s*\d+\s*)*)\]",
                    "",
                    provider_answer,
                )
                provider_notes.append(
                    f"### {step['label']}\n{provider_answer}"
                )
            yield f"data: {json.dumps({'type': 'research_step', 'step_id': step['id'], 'index': index, 'status': 'done', 'label': step['label'], 'result_count': len(report.get('results', [])), 'engine': report.get('engine')})}\n\n"

        evidence = merge_research_results(reports)
        selected_file_ids = _resolve_selected_rag_file_ids(
            req.selected_file_ids,
            req.project_id,
        )
        document_evidence = deps.rag_store.search_scopes(
            [req.project_id],
            req.question,
            top_k=10,
            file_ids=selected_file_ids or None,
        )
        yield f"data: {json.dumps({'type': 'research_synthesis', 'status': 'running', 'result_count': len(evidence), 'web_results': evidence})}\n\n"
        evidence_context = format_search_results(evidence)
        provider_context = "\n\n".join(provider_notes)
        document_context = "\n\n".join(
            (
                f"<document name=\"{chunk['doc_name']}\" "
                f"file_id=\"{chunk.get('file_id') or ''}\" "
                f"page=\"{chunk.get('page') or 1}\" "
                f"section=\"{chunk.get('section') or ''}\">\n"
                f"{chunk['content']}\n</document>"
            )
            for chunk in document_evidence
        )
        prompt = [
            {
                "role": "system",
                "content": (
                    "Tu rédiges un rapport de recherche approfondie en français. "
                    "Commence par une réponse synthétique, puis présente les faits "
                    "établis, les nuances ou désaccords, et une conclusion. Chaque "
                    "affirmation issue des preuves doit citer [n]. N'invente aucune "
                    "source, date, statistique ou citation. Indique clairement les "
                    "limites des preuves. Pour un fait provenant d'un document du "
                    "projet, cite "
                    "[Document : nom, p. X]{file:identifiant} en recopiant le "
                    "file_id fourni. Compare les documents "
                    "internes aux sources externes lorsqu'ils couvrent le même fait. "
                    "Utilise un Markdown sobre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question de recherche : {req.question}\n\n"
                    f"Notes issues des recherches :\n{provider_context}\n\n"
                    f"Sources numérotées :\n{evidence_context}\n\n"
                    f"Documents du projet :\n{document_context or 'Aucun document pertinent.'}"
                ),
            },
        ]
        profile = get_model_profile(selected_model)
        full_report = ""
        async for chunk in deps.client.stream_chat(
            model=selected_model,
            messages=prompt,
            temperature=min(profile.temperature, 0.25),
            num_ctx=profile.num_ctx,
            num_predict=min(profile.num_predict, 7_000),
            options=profile.options,
            think=profile.think,
        ):
            if chunk.get("_error"):
                yield f"data: {json.dumps({'type': 'error', 'message': 'La synthèse locale a échoué.', 'error_type': chunk['_error']})}\n\n"
                yield "data: [DONE]\n\n"
                return
            delta = clean_model_text(chunk.get("message", {}).get("content", ""))
            if delta:
                full_report += delta
                yield f"data: {json.dumps({'type': 'content_delta', 'content': delta})}\n\n"

        if full_report and not req.temporary:
            assistant_message_id = deps.db.add_message(
                session_id,
                "assistant",
                full_report,
                metadata={
                    **compact_web_source_metadata(evidence),
                    "mode": "deep_research",
                },
            )
            artifact = deps.artifact_store.create(
                project_id=req.project_id,
                session_id=session_id,
                source_message_id=assistant_message_id,
                title=f"Recherche · {req.question[:100]}",
                content=full_report,
                kind="research",
            )
            yield f"data: {json.dumps({'type': 'message_saved', 'role': 'assistant', 'message_id': assistant_message_id})}\n\n"
            yield f"data: {json.dumps({'type': 'research_done', 'artifact_id': artifact.get('id'), 'result_count': len(evidence), 'web_results': evidence})}\n\n"
        elif full_report:
            yield f"data: {json.dumps({'type': 'research_done', 'artifact_id': None, 'result_count': len(evidence), 'web_results': evidence, 'temporary': True})}\n\n"
        if is_new_session:
            deps.job_store.enqueue(
                "title",
                {"session_id": session_id, "prompt": req.question, "model": selected_model},
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(research_events(), media_type="text/event-stream")
