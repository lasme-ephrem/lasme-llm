"""Racine de composition de l'API Lasme LLM (refonte modulaire).

L'ancien monolithe de ~4 300 lignes est découpé en modules :

- ``chat.contracts``       — schémas Pydantic + contrat SSE versionné ;
- ``chat.server.services`` — texte, sources, stats, heuristiques, tâches de fond ;
- ``chat.server.modules``  — routes HTTP par domaine (workspace, documents,
  files, artifacts, runner, research, chat, coding, media) ;
- ``chat.server.app``      — la factory ``create_app`` (middlewares, routers) ;
- ``chat.server.deps``     — l'injection de dépendances (plus de singletons).

Ce shim garde deux choses pour compatibilité :

1. les **symboles historiques** importés par la suite de tests
   (``from chat.server.main import …``, ``server_main.db``…) ;
2. le **middleware de sécurité** : ses fonctions sont patchées par les tests
   via le chemin ``chat.server.main.*``, il doit donc vivre dans ce module.
"""

from __future__ import annotations

import time  # noqa: F401  (patché par les tests : server_main.time.monotonic)

from fastapi import Request
from fastapi.responses import JSONResponse

from chat.contracts.schemas import (  # noqa: F401
    AgentRunRequest,
    ChatMessage,
    ChatRequest,
    ImageGenerateRequest,
    is_model_available as _model_is_available,
    model_key as _model_key,
    validate_model_name as _validate_model_name,
)
from chat.server.app import create_app
from chat.server.deps import build_deps, deps
from chat.server.modules.chat.routes import (  # noqa: F401
    chat_stream,
    detect_image_intent,
)
from chat.server.modules.documents.indexing import (  # noqa: F401
    _index_project_image,
    _index_project_pdf,
)
from chat.server.modules.documents.routes import (  # noqa: F401
    _resolve_selected_rag_file_ids,
)
from chat.server.services.background import (  # noqa: F401
    async_generate_and_update_title,
    async_update_conversation_memory,
    async_update_personal_memory,
    sanitize_generated_title,
)
from chat.server.services.heuristics import (  # noqa: F401
    _fallback_contextual_search_query,
    is_recency_sensitive,
    is_simple_factual_lookup,
    is_social_turn,
    response_depth_instruction,
    response_presentation_profile,
    should_enable_reasoning,
)
from chat.server.services.sources import (  # noqa: F401
    extract_agent_sources,
    merge_dedup_sources,
    normalize_source_url,
)
from chat.server.services.stats import build_generation_stats  # noqa: F401
from chat.server.services.text import (  # noqa: F401
    clean_model_text,
    compact_web_source_metadata,
    iter_stream_text_chunks,
    sanitize_citation_markers,
    strip_web_citation_markers,
    unsupported_grounded_numbers,
)
from coding.agent import LasmeCodingAgent  # noqa: F401
from core.config import settings
from core.inference.client import LasmeLLMClient
from core.security import (
    configured_access_token,
    is_direct_local_request,
    request_has_valid_query_token,
    request_has_valid_token,
)

# --- Dépendances partagées (compat : mêmes objets que avant la refacto) ---
deps = build_deps()
client = deps.bind_client(LasmeLLMClient())
db = deps.db
rag_store = deps.rag_store
project_file_store = deps.project_file_store
artifact_store = deps.artifact_store
python_runner = deps.python_runner


# --- Frontière de sécurité (patchée par les tests via ce chemin) -----------
async def protect_remote_api(request: Request, call_next):
    """Keep local UX frictionless while requiring a token through any tunnel."""
    valid_query_token = request_has_valid_query_token(request)
    protected_path = (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/generated_images/")
    )
    if protected_path:
        is_local = is_direct_local_request(request)
        has_token = request_has_valid_token(request)
        if not is_local and not has_token:
            secure_token = configured_access_token()
            message = (
                "Remote API access is disabled until LASME_ACCESS_TOKEN is "
                "configured with a strong random value and supplied."
                if not secure_token
                else "A valid Lasme access token is required."
            )
            return JSONResponse({"detail": message}, status_code=401)
        if (
            request.url.path.startswith("/api/coding/")
            and not is_local
            and not settings.allow_remote_coding
        ):
            return JSONResponse(
                {"detail": "Coding and terminal APIs are local-only."},
                status_code=403,
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    is_project_file_preview = (
        request.url.path.startswith("/api/files/")
        and request.url.path.endswith("/content")
    )
    is_artifact_preview = request.url.path.startswith("/api/artifact-previews/")
    response.headers.setdefault(
        "X-Frame-Options",
        "SAMEORIGIN"
        if is_project_file_preview or is_artifact_preview
        else "DENY",
    )
    if valid_query_token:
        secure_token = configured_access_token()
        response.set_cookie(
            key="lasme_access_token",
            value=secure_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=8 * 60 * 60,
            path="/",
        )
    return response


app = create_app(deps, http_dispatch=protect_remote_api)
