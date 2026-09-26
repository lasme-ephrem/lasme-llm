"""Factory applicative FastAPI : middlewares, routers, statiques, lifespan.

C'est le POINT D'ENTRÉE architectural de l'API : ``main.py`` ne fait que
câbler les dépendances et appeler ``create_app``. Aucune route n'est
définie ici — elles vivent dans ``chat/server/modules/``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from chat.contracts.schemas import is_model_available, validate_model_name
from chat.server.deps import Deps, deps
from chat.server.modules.artifacts.routes import router as artifacts_router
from chat.server.modules.chat.routes import router as chat_router
from chat.server.modules.coding.routes import router as coding_router
from chat.server.modules.documents.routes import router as documents_router
from chat.server.modules.files.routes import router as files_router
from chat.server.modules.media.routes import router as media_router
from chat.server.modules.research.routes import router as research_router
from chat.server.modules.runner.routes import router as runner_router
from chat.server.modules.workspace.routes import router as workspace_router
from chat.server.routers.agent import AgentDeps, create_agent_router
from chat.server.routers.meta import MetaDeps, create_meta_router
from core.artifacts import EXPORT_FORMATS
from core.config import settings
from core.memory.database import DEFAULT_PROJECT_ID
from core.tools.image_generator import IMAGES_DIR


async def build_capabilities(dependencies: Deps = deps) -> dict:
    try:
        installed_models = [
            str(model.get("name") or "")
            for model in await dependencies.client.list_models()
            if model.get("name")
        ]
    except Exception:
        installed_models = []
    return {
        "vision_enabled": is_model_available(
            settings.vision_model, installed_models
        ),
        "vision_model": settings.vision_model,
        "fast_model": settings.fast_model,
        "fast_model_enabled": is_model_available(
            settings.fast_model, installed_models
        ),
        "installed_models": installed_models,
        "ocr": dependencies.rag_store.ocr_capabilities(),
        "external_image_generation_enabled": settings.external_image_generation_enabled,
        "remote_coding_enabled": settings.allow_remote_coding,
        "agent_terminal_enabled": settings.agent_terminal_enabled,
        "python_runner_enabled": await dependencies.python_runner.available(),
        "projects_enabled": True,
        "project_file_library_enabled": True,
        "supported_project_files": [
            "pdf", "txt", "md", "docx", "xlsx", "pptx",
            "png", "jpg", "jpeg", "webp",
        ],
        "canvas_enabled": True,
        "artifact_exports": sorted(EXPORT_FORMATS),
        "deep_research_enabled": True,
        "hybrid_rag_enabled": True,
    }


def create_app(
    dependencies: Deps,
    http_dispatch: Optional[Callable] = None,
) -> FastAPI:
    """Construit l'application complète à partir des dépendances fournies.

    ``http_dispatch`` est le middleware de sécurité : il est injecté par
    ``main.py`` (racine de composition) pour que les tests puissent patcher
    ses fonctions via le chemin historique ``chat.server.main``.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Worker de jobs de fond en process (le même loop tourne aussi en
        # process séparé via `python -m chat.worker`).
        import asyncio
        import datetime
        import time as _time

        from chat.worker.loop import worker_loop

        last_beat = 0.0

        def _heartbeat() -> None:
            nonlocal last_beat
            now = _time.monotonic()
            if now - last_beat < 10:
                return
            last_beat = now
            try:
                dependencies.db.set_setting(
                    "worker_heartbeat",
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                )
            except Exception:
                pass

        worker_task = asyncio.create_task(worker_loop(heartbeat=_heartbeat))
        try:
            yield
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                pass
            # Arrêt propre : rapatrier le journal WAL dans le fichier
            # principal avant fermeture (jamais supprimer -wal/-shm).
            try:
                dependencies.db.checkpoint()
            except Exception:
                pass
            await dependencies.client.aclose()

    app = FastAPI(title="Lasme LLM API", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Lasme-Token"],
    )
    if http_dispatch is not None:
        app.add_middleware(BaseHTTPMiddleware, dispatch=http_dispatch)

    # Routers métier (un module = un domaine).
    app.include_router(workspace_router)
    app.include_router(documents_router)
    app.include_router(files_router)
    app.include_router(artifacts_router)
    app.include_router(runner_router)
    app.include_router(research_router)
    app.include_router(chat_router)
    app.include_router(coding_router)
    app.include_router(media_router)

    # Routers transverses (health/meta + console agent autonome).
    app.include_router(create_meta_router(MetaDeps(
        client=dependencies.client,
        db=dependencies.db,
        python_runner=dependencies.python_runner,
        rag_store=dependencies.rag_store,
        settings=settings,
        app_version=app.version,
        capabilities_builder=lambda: build_capabilities(dependencies),
    )))
    app.include_router(create_agent_router(AgentDeps(
        client=dependencies.client,
        db=dependencies.db,
        python_runner=dependencies.python_runner,
        rag_store=dependencies.rag_store,
        file_store=dependencies.project_file_store,
        artifact_store=dependencies.artifact_store,
        vision_model=settings.vision_model,
        default_project_id=DEFAULT_PROJECT_ID,
        validate_model=validate_model_name,
    )))

    # Serve Generated Images
    if IMAGES_DIR.exists():
        app.mount("/generated_images", StaticFiles(directory=str(IMAGES_DIR)), name="generated_images")

    # Serve Web Frontend Static Files
    frontend_dir = Path(__file__).resolve().parent.parent / "web"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

    return app
