"""Meta endpoints: health, models, capabilities, static identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter


@dataclass
class MetaDeps:
    client: Any                  # LasmeLLMClient
    db: Any                      # DatabaseManager
    python_runner: Any
    rag_store: Any
    settings: Any
    app_version: str
    capabilities_builder: Callable[[], dict]


def create_meta_router(deps: MetaDeps) -> APIRouter:
    router = APIRouter(tags=["meta"])

    @router.get("/api/health")
    async def health_check():
        checks: dict = {
            "database": {"status": "ok", "required": True},
            "ollama": {
                "status": "unknown",
                "models": [],
                "required": True,
            },
        }
        try:
            deps.db.list_sessions()
        except Exception as exc:
            checks["database"] = {
                "status": "error",
                "error": type(exc).__name__,
                "required": True,
            }
        try:
            models = await deps.client.list_models()
            model_names = [
                str(model.get("name") or "")
                for model in models
                if model.get("name")
            ]
            normalized = {
                name.removesuffix(":latest") for name in model_names
            }
            required_models = list(
                dict.fromkeys(
                    [
                        deps.settings.chat_model,
                        deps.settings.fast_model,
                        deps.settings.vision_model,
                    ]
                )
            )
            missing_models = [
                model
                for model in required_models
                if model.removesuffix(":latest") not in normalized
            ]
            checks["ollama"] = {
                "status": "ok" if not missing_models else "error",
                "models": model_names,
                "required_models": required_models,
                "missing_models": missing_models,
                "required": True,
            }
        except Exception as exc:
            checks["ollama"] = {
                "status": "error",
                "error": type(exc).__name__,
                "required": True,
            }
        runner_available = await deps.python_runner.available()
        checks["runner"] = {
            "status": "ok" if runner_available else "unavailable",
            "required": True,
            "engine": "docker",
        }
        ocr = deps.rag_store.ocr_capabilities()
        checks["ocr"] = {
            "status": "ok" if ocr.get("available") else "unavailable",
            "required": False,
            **ocr,
        }
        overall = (
            "ok"
            if all(
                check["status"] == "ok"
                for check in checks.values()
                if check.get("required", True)
            )
            else "degraded"
        )
        return {
            "status": overall,
            "server": "LasmeLLM local API",
            "version": deps.app_version,
            "checks": checks,
        }

    @router.get("/api/models")
    async def get_models():
        models = await deps.client.list_models()
        return {"models": models}

    @router.get("/api/capabilities")
    async def get_capabilities():
        return await deps.capabilities_builder()

    return router
