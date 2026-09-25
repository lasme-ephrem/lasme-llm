"""Indexation documentaire RAG (images vision, PDF parser+vision)."""

from __future__ import annotations

import asyncio
import base64
import datetime
from typing import Any, Dict, List, Optional

from chat.server.deps import deps
from chat.server.services.text import clean_model_text

_document_indexing_semaphore = asyncio.Semaphore(1)


async def _index_project_image(
    *,
    scope_id: str,
    filename: str,
    content: bytes,
    file_id: str,
    mime_type: str,
) -> tuple[int, Dict[str, Any]]:
    """Describe and index an image with the local vision model.

    OCR remains a fallback for installations where the vision model is not
    available. The stored original is never modified.
    """
    encoded = base64.b64encode(content).decode("ascii")
    prompt = (
        "Analyse cette image destinée à une base documentaire RAG. "
        "Retourne uniquement une transcription et une description factuelles, "
        "en français, structurées avec les rubriques suivantes lorsqu'elles "
        "sont pertinentes : TEXTE VISIBLE, DESCRIPTION, DONNÉES STRUCTURÉES, "
        "GRAPHIQUE OU SCHÉMA, ÉLÉMENTS INCERTAINS. Transcris fidèlement tous "
        "les textes lisibles. Pour un tableau, restitue les en-têtes et les "
        "lignes. Pour un graphique, relève les axes, légendes, valeurs et "
        "tendances visibles. N'invente aucune information absente de l'image."
    )
    try:
        reply = await asyncio.wait_for(
            deps.client.chat(
                model=deps.settings.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [encoded],
                    }
                ],
                temperature=0.0,
                think=False,
                num_ctx=8_192,
                num_predict=2_048,
            ),
            timeout=120.0,
        )
        analysis = clean_model_text(
            reply.get("message", {}).get("content", "")
        ).strip()
        if not analysis:
            raise ValueError("The vision model returned an empty analysis.")
        chunks = await asyncio.to_thread(
            deps.rag_store.add_extracted_text,
            scope_id,
            filename,
            analysis,
            file_id=file_id,
            mime_type=mime_type,
            section_title="Analyse visuelle",
        )
        return chunks, {
            "indexer": "vision",
            "vision_model": deps.settings.vision_model,
            "visual_analysis": analysis[:4_000],
        }
    except Exception as vision_error:
        chunks = await asyncio.to_thread(
            deps.rag_store.add_document,
            scope_id,
            filename,
            content,
            file_id=file_id,
            mime_type=mime_type,
        )
        return chunks, {
            "indexer": "ocr_fallback",
            "vision_error": type(vision_error).__name__,
        }


async def _index_project_pdf(
    *,
    scope_id: str,
    filename: str,
    content: bytes,
    file_id: str,
    mime_type: str,
) -> tuple[int, Dict[str, Any]]:
    """Index PDF text first and reserve Vision for documents without text.

    Text PDFs are made searchable immediately. Running a vision model on every
    chart or illustration used to keep the upload request open for minutes and
    made simultaneous imports compete with chat inference. Scanned PDFs still
    use the vision fallback because it is required to obtain any usable text.
    """
    parser_error: Optional[Exception] = None
    parser_chunks = 0
    try:
        parser_chunks = await asyncio.to_thread(
            deps.rag_store.add_document,
            scope_id,
            filename,
            content,
            file_id=file_id,
            mime_type=mime_type,
        )
    except ValueError as exc:
        parser_error = exc

    if parser_chunks:
        return parser_chunks, {
            "indexer": "document_parser",
            "vision_status": "not_required",
        }

    try:
        rendered_pages, total_pages = await asyncio.to_thread(
            deps.rag_store.render_pdf_pages_for_vision,
            content,
        )
    except ValueError:
        rendered_pages, total_pages = [], 0

    analyses: List[tuple[int, str, str]] = []
    vision_errors: List[str] = []
    if rendered_pages and deps.settings.vision_model:
        semaphore = asyncio.Semaphore(2)

        async def analyze_page(
            page_number: int,
            png: bytes,
            reason: str,
        ) -> tuple[int, str, str] | Exception:
            prompt = (
                f"Analyse factuellement la page {page_number} sur "
                f"{total_pages} de ce PDF. "
                "Transcris tout texte visible et décris précisément les "
                "tableaux, graphiques, axes, légendes, valeurs, schémas et "
                "illustrations utiles. N'invente rien. Structure la réponse "
                "en TEXTE VISIBLE, DONNÉES STRUCTURÉES et ÉLÉMENTS VISUELS. "
                f"Type de page détecté : {reason}."
            )
            try:
                async with semaphore:
                    reply = await asyncio.wait_for(
                        deps.client.chat(
                            model=deps.settings.vision_model,
                            messages=[
                                {
                                    "role": "user",
                                    "content": prompt,
                                    "images": [
                                        base64.b64encode(png).decode("ascii")
                                    ],
                                }
                            ],
                            temperature=0.0,
                            think=False,
                            num_ctx=8_192,
                            num_predict=1_536,
                        ),
                        timeout=90.0,
                    )
                analysis = clean_model_text(
                    reply.get("message", {}).get("content", "")
                ).strip()
                if not analysis:
                    raise ValueError("Empty visual PDF analysis.")
                return (
                    page_number,
                    f"Page {page_number} · analyse visuelle",
                    analysis,
                )
            except Exception as exc:
                return exc

        page_results = await asyncio.gather(
            *[
                analyze_page(page_number, png, reason)
                for page_number, png, reason in rendered_pages
            ]
        )
        for result in page_results:
            if isinstance(result, Exception):
                vision_errors.append(type(result).__name__)
            else:
                analyses.append(result)

    visual_chunks = 0
    if analyses:
        if parser_chunks:
            visual_chunks = await asyncio.to_thread(
                deps.rag_store.append_extracted_pages,
                file_id,
                analyses,
            )
        else:
            visual_chunks = await asyncio.to_thread(
                deps.rag_store.add_extracted_pages,
                scope_id,
                filename,
                analyses,
                file_id=file_id,
                mime_type=mime_type,
            )
    elif parser_error is not None:
        raise ValueError(
            "Le PDF ne contient aucun texte extractible et l'analyse Vision "
            "n'a pas pu produire de transcription."
        ) from parser_error

    return parser_chunks + visual_chunks, {
        "indexer": (
            "document_parser+vision"
            if analyses and parser_chunks
            else ("vision_pdf" if analyses else "document_parser")
        ),
        "vision_model": deps.settings.vision_model if analyses else "",
        "vision_pages": [page[0] for page in analyses],
        "vision_page_limit": len(rendered_pages),
        "total_pages": total_pages,
        "vision_errors": vision_errors[:10],
    }


async def _index_stored_project_file(
    *,
    scope_id: str,
    filename: str,
    content: bytes,
    stored_file: Dict[str, Any],
) -> Dict[str, Any]:
    """Build one searchable project index without blocking other imports."""
    async with _document_indexing_semaphore:
        try:
            indexing_metadata: Dict[str, Any] = {}
            if stored_file.get("kind") == "image" and deps.settings.vision_model:
                chunks_added, indexing_metadata = await _index_project_image(
                    scope_id=scope_id,
                    filename=filename,
                    content=content,
                    file_id=stored_file["id"],
                    mime_type=stored_file["mime_type"],
                )
            elif stored_file.get("kind") == "pdf":
                chunks_added, indexing_metadata = await _index_project_pdf(
                    scope_id=scope_id,
                    filename=filename,
                    content=content,
                    file_id=stored_file["id"],
                    mime_type=stored_file["mime_type"],
                )
            else:
                chunks_added = await asyncio.to_thread(
                    deps.rag_store.add_document,
                    scope_id,
                    filename,
                    content,
                    file_id=stored_file["id"],
                    mime_type=stored_file["mime_type"],
                )
                indexing_metadata = {"indexer": "document_parser"}
            document = next(
                (
                    item
                    for item in deps.rag_store.list_documents(scope_id)
                    if item.get("file_id") == stored_file["id"]
                ),
                {},
            )
            return deps.project_file_store.update(
                stored_file["id"],
                status="ready",
                page_count=int(document.get("page_count") or 0),
                chunk_count=chunks_added,
                error="",
                metadata={
                    "indexed_at": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                    **indexing_metadata,
                },
            ) or stored_file
        except Exception as exc:
            deps.project_file_store.update(
                stored_file["id"],
                status="error",
                error=str(exc),
            )
            raise


async def _index_project_file_in_background(
    *,
    scope_id: str,
    filename: str,
    content: bytes,
    stored_file: Dict[str, Any],
) -> None:
    """Background wrapper: retain a per-file error instead of failing a batch."""
    try:
        await _index_stored_project_file(
            scope_id=scope_id,
            filename=filename,
            content=content,
            stored_file=stored_file,
        )
    except Exception:
        # The exact error is persisted on the file record and surfaced by the
        # project library. One failed file must never cancel sibling imports.
        return
