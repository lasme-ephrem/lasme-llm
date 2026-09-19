"""Agent tools over the platform stores: RAG, sandboxed Python, files, vision.

Dependencies are injected at build time so the module stays testable and
avoids import cycles with the chat server.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.agent.tools import (
    CATEGORY_EXEC,
    CATEGORY_READ,
    ToolDefinition,
    ToolRegistry,
)

MAX_RAG_OUTPUT = 6_000
MAX_FILE_OUTPUT = 8_000


def _format_rag_results(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return (
            "Aucun passage trouvé dans les documents du projet. "
            "Propose d'importer le document ou utilise web_search."
        )
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        name = chunk.get("doc_name") or chunk.get("filename") or "document"
        page = chunk.get("page_number")
        locator = f", p. {page}" if page else ""
        content = str(chunk.get("content") or chunk.get("chunk_text") or "").strip()
        if len(content) > 900:
            content = content[:900] + "…"
        lines.append(
            f"[Document : {name}{locator}]\n{content}"
        )
    return "\n\n".join(lines)[:MAX_RAG_OUTPUT]


def register_platform_tools(
    registry: ToolRegistry,
    *,
    rag_search_fn: Optional[Any] = None,
    python_runner: Optional[Any] = None,
    file_store: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    vision_model: str = "gemma-4-12b",
    prebound_image: Optional[str] = None,
) -> None:
    if rag_search_fn is not None:
        async def _rag_search(args: Dict[str, Any]) -> str:
            top_k = int(args.get("top_k") or 4)
            results = await rag_search_fn(args["query"], top_k)
            return _format_rag_results(results)

        registry.register(
            ToolDefinition(
                name="rag_search",
                description=(
                    "Recherche dans les documents importés du projet "
                    "(PDF, Word, Excel, Markdown). Retourne des passages "
                    "avec citation du fichier et de la page."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {
                            "type": "integer",
                            "enum": [1, 2, 3, 4, 5, 6, 8],
                        },
                    },
                    "required": ["query"],
                },
                handler=_rag_search,
                category=CATEGORY_READ,
                timeout_s=30.0,
                max_output_chars=MAX_RAG_OUTPUT,
            )
        )

    if python_runner is not None:
        async def _python_run(args: Dict[str, Any]) -> str:
            result = await python_runner.run(
                str(args["code"]),
                timeout_seconds=int(args.get("timeout_seconds") or 30),
            )
            parts = [
                f"status: {result.status} (exit {result.exit_code}, "
                f"{result.duration_ms} ms)"
            ]
            if result.stdout:
                parts.append(f"stdout:\n{result.stdout}")
            if result.stderr:
                parts.append(f"stderr:\n{result.stderr}")
            if result.files:
                names = ", ".join(
                    str(f.get("name") or f.get("path") or "?")
                    for f in result.files[:10]
                )
                parts.append(f"fichiers produits: {names}")
            return "\n".join(parts)

        registry.register(
            ToolDefinition(
                name="python_run",
                description=(
                    "Exécute du code Python dans un bac à sable Docker "
                    "isolé (sans réseau). matplotlib/numpy/pandas/openpyxl "
                    "disponibles. Retourne stdout, stderr et les fichiers "
                    "produits."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Code Python"},
                        "timeout_seconds": {
                            "type": "integer",
                            "enum": [10, 20, 30, 60],
                        },
                    },
                    "required": ["code"],
                },
                handler=_python_run,
                category=CATEGORY_EXEC,
                timeout_s=90.0,
                max_output_chars=6_000,
            )
        )

    if file_store is not None:
        async def _files_list(args: Dict[str, Any]) -> str:
            files = file_store.list(args.get("project_id") or "default")
            if not files:
                return "Aucun fichier dans ce projet."
            rows = [
                f"- {f.get('id')} | {f.get('filename')} | "
                f"{f.get('mime_type') or '?'} | "
                f"{int(f.get('size') or 0)} octets"
                for f in files[:40]
            ]
            return "\n".join(rows)

        async def _files_read_text(args: Dict[str, Any]) -> str:
            raw = file_store.read(args["file_id"])
            text = raw.decode("utf-8", errors="replace")
            limit = int(args.get("max_chars") or 6000)
            if len(text) > limit:
                text = text[:limit] + f"\n…[tronqué à {limit} caractères]"
            return text or "(fichier vide)"

        registry.register(
            ToolDefinition(
                name="files_list",
                description=(
                    "Liste les fichiers importés du projet avec leurs ids."
                ),
                parameters={
                    "type": "object",
                    "properties": {"project_id": {"type": "string"}},
                    "required": [],
                },
                handler=_files_list,
                category=CATEGORY_READ,
                timeout_s=15.0,
            )
        )
        registry.register(
            ToolDefinition(
                name="files_read_text",
                description=(
                    "Lit le contenu texte d'un fichier du projet "
                    "(utilise files_list pour obtenir les ids)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "max_chars": {"type": "integer", "enum": [1000, 3000, 6000, 12000]},
                    },
                    "required": ["file_id"],
                },
                handler=_files_read_text,
                category=CATEGORY_READ,
                timeout_s=15.0,
                max_output_chars=MAX_FILE_OUTPUT,
            )
        )

    if vision_client is not None:
        async def _analyze_image(args: Dict[str, Any]) -> str:
            image = args.get("image_base64") or prebound_image or ""
            message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": str(args["question"])},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image}"},
                    },
                ],
            }
            response = await vision_client.chat(
                vision_model,
                [message],
                think=False,
                num_predict=int(args.get("max_tokens") or 700),
            )
            return response["message"]["content"] or "(aucune réponse)"

        properties: Dict[str, Any] = {
            "question": {"type": "string"},
            "max_tokens": {"type": "integer", "enum": [300, 700, 1500]},
        }
        required = ["question"]
        description = (
            "Analyse l'image jointe à la mission (photo, capture, diagramme, "
            "tableau) avec le modèle de vision local. Pose la question "
            "précise à répondre sur l'image."
        )
        if not prebound_image:
            properties["image_base64"] = {
                "type": "string",
                "description": "Image encodée en base64",
            }
            required = ["image_base64", "question"]
            description = (
                "Analyse une image (photo, capture, diagramme, tableau) "
                "avec le modèle de vision local. Fournis la question "
                "précise à répondre sur l'image."
            )

        registry.register(
            ToolDefinition(
                name="analyze_image",
                description=description,
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
                handler=_analyze_image,
                category=CATEGORY_READ,
                timeout_s=120.0,
                max_output_chars=4_000,
            )
        )
