"""Schémas de requêtes HTTP + catalogue de modèles autorisés.

Extraits de ``chat/server/main.py`` (refonte modulaire) : comportement
identique, typage centralisé.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from core.config import settings
from core.inference.profiles import LEGACY_MODEL_ALIASES, RUNTIME_PROFILES
from core.memory.database import DEFAULT_PROJECT_ID


# --- Catalogue de modèles -------------------------------------------------
def allowed_model_names() -> set[str]:
    return {
        name
        for name in {
            settings.chat_model,
            settings.coding_model,
            settings.reasoning_model,
            settings.fast_model,
            settings.vision_model,
            *settings.extra_models,
            # v2 runtime profiles plus every legacy name still stored in
            # old sessions/projects; the inference client resolves them.
            *RUNTIME_PROFILES,
            *LEGACY_MODEL_ALIASES,
        }
        if name
    }


def model_key(name: str) -> str:
    return str(name or "").strip().removesuffix(":latest")


def is_model_available(model: str, available: List[str]) -> bool:
    expected = model_key(model)
    return bool(expected) and any(
        model_key(candidate) == expected
        for candidate in available
    )


def validate_model_name(model: str) -> str:
    if model not in allowed_model_names():
        raise HTTPException(
            status_code=400,
            detail=f"Model is not allowed: {model}",
        )
    return model


# Alias historiques (noms utilisés dans l'ancien monolithe et les tests).
_allowed_model_names = allowed_model_names
_model_key = model_key
_model_is_available = is_model_available


# --- Schémas de requêtes --------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=100_000)
    images: Optional[List[str]] = Field(default=None, max_length=4)

    @field_validator("images")
    @classmethod
    def validate_image_payload(cls, images: Optional[List[str]]):
        if images:
            encoded_limit = int(settings.max_upload_bytes * 1.4) + 256
            if any(len(image) > encoded_limit for image in images):
                raise ValueError("Image attachment exceeds the configured size limit.")
            if sum(len(image) for image in images) > encoded_limit * 2:
                raise ValueError("Combined image attachments exceed the configured limit.")
        return images


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    project_id: Optional[str] = DEFAULT_PROJECT_ID
    document_scope_id: Optional[str] = None
    selected_file_ids: List[str] = Field(default_factory=list, max_length=20)
    model: Optional[str] = settings.chat_model
    messages: List[ChatMessage] = Field(min_length=1, max_length=200)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    intelligence_level: Optional[str] = "high"
    web_search_enabled: Optional[bool] = True
    web_search_mode: Optional[str] = "auto"
    persist_user_message: bool = True
    temporary: bool = False


class AgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    model: Optional[str] = settings.coding_model


class SessionCreateRequest(BaseModel):
    title: str = Field(default="Nouvelle Conversation", max_length=120)
    model: str = Field(default=settings.chat_model, max_length=100)
    project_id: str = Field(default=DEFAULT_PROJECT_ID, max_length=100)


class SessionUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    project_id: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, max_length=100)
    pinned: Optional[bool] = None


class SessionImportRequest(BaseModel):
    bundle: Dict[str, Any]
    project_id: Optional[str] = Field(default=None, max_length=100)


class ChatCompareVariant(BaseModel):
    model: str = Field(default=settings.chat_model, max_length=100)
    effort: Literal["low", "medium", "high"] = "high"
    label: Optional[str] = Field(default=None, max_length=80)


class ChatCompareRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    session_id: Optional[str] = Field(default=None, max_length=100)
    left: ChatCompareVariant = Field(default_factory=lambda: ChatCompareVariant(model=settings.fast_model, effort="low"))
    right: ChatCompareVariant = Field(default_factory=lambda: ChatCompareVariant(model=settings.chat_model, effort="high"))


class AudioTranscribeRequest(BaseModel):
    audio_base64: Optional[str] = Field(default=None, max_length=15_000_000)
    text_hint: Optional[str] = Field(default=None, max_length=10_000)
    language: str = Field(default="fr-FR", max_length=20)


class MissionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    prompt: str = Field(min_length=1, max_length=20_000)
    project_id: str = Field(default=DEFAULT_PROJECT_ID, max_length=100)
    model: str = Field(default=settings.chat_model, max_length=100)
    schedule_label: str = Field(default="Quotidien · 08:00", max_length=80)
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    enabled: bool = True


class MissionUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=140)
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=20_000)
    project_id: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, max_length=100)
    schedule_label: Optional[str] = Field(default=None, max_length=80)
    interval_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    enabled: Optional[bool] = None


class MessageUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class BranchRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)
    content: Optional[str] = Field(default=None, max_length=100_000)
    model: Optional[str] = Field(default=None, max_length=100)


class MessageEditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=8_000)
    default_model: str = Field(default=settings.chat_model, max_length=100)
    memory_mode: Literal["project", "global", "off"] = "project"
    project_type: Literal[
        "general",
        "research",
        "learning",
        "data",
        "coding",
        "writing",
        "media",
    ] = "general"
    tags: List[str] = Field(default_factory=list, max_length=12)
    color: str = Field(default="", max_length=7)
    favorite: bool = False

    @field_validator("tags")
    @classmethod
    def validate_project_tags(cls, tags: List[str]) -> List[str]:
        return [
            normalized
            for normalized in (
                str(tag).strip()[:32]
                for tag in tags
            )
            if normalized
        ][:12]

    @field_validator("color")
    @classmethod
    def validate_project_color(cls, color: str) -> str:
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Project color must use #RRGGBB.")
        return color


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    instructions: Optional[str] = Field(default=None, max_length=8_000)
    default_model: Optional[str] = Field(default=None, max_length=100)
    memory_mode: Optional[Literal["project", "global", "off"]] = None
    project_type: Optional[
        Literal[
            "general",
            "research",
            "learning",
            "data",
            "coding",
            "writing",
            "media",
        ]
    ] = None
    tags: Optional[List[str]] = Field(default=None, max_length=12)
    color: Optional[str] = Field(default=None, max_length=7)
    favorite: Optional[bool] = None

    @field_validator("tags")
    @classmethod
    def validate_updated_project_tags(
        cls,
        tags: Optional[List[str]],
    ) -> Optional[List[str]]:
        if tags is None:
            return None
        return [
            normalized
            for normalized in (
                str(tag).strip()[:32]
                for tag in tags
            )
            if normalized
        ][:12]

    @field_validator("color")
    @classmethod
    def validate_updated_project_color(
        cls,
        color: Optional[str],
    ) -> Optional[str]:
        if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Project color must use #RRGGBB.")
        return color


class ProjectFileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=180)


class ArtifactCreateRequest(BaseModel):
    project_id: str = Field(default=DEFAULT_PROJECT_ID, max_length=100)
    session_id: Optional[str] = Field(default=None, max_length=100)
    source_message_id: Optional[str] = Field(default=None, max_length=100)
    title: str = Field(default="Sans titre", max_length=160)
    content: str = Field(default="", max_length=1_000_000)
    kind: Literal[
        "document",
        "code",
        "markdown",
        "table",
        "research",
        "html",
        "interactive",
        "diagram",
        "mindmap",
        "chart",
        "presentation",
    ] = "document"
    language: str = Field(default="", max_length=40)


class ArtifactUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)
    content: str = Field(max_length=1_000_000)
    change_summary: str = Field(default="", max_length=240)
    kind: Optional[Literal[
        "document",
        "code",
        "markdown",
        "table",
        "research",
        "html",
        "interactive",
        "diagram",
        "mindmap",
        "chart",
        "presentation",
    ]] = None


class ArtifactPreviewRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)


class PythonRunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)
    timeout_seconds: int = Field(default=15, ge=1, le=20)
    inputs: Dict[str, Any] = Field(default_factory=dict)


class DeepResearchRequest(BaseModel):
    session_id: Optional[str] = None
    project_id: str = Field(default=DEFAULT_PROJECT_ID, max_length=100)
    question: str = Field(min_length=3, max_length=20_000)
    model: Optional[str] = settings.reasoning_model
    intelligence_level: Optional[str] = "high"
    selected_file_ids: List[str] = Field(default_factory=list, max_length=20)
    temporary: bool = False


class MemorySettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_save: Optional[bool] = None


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=300)


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=300)
    enabled: Optional[bool] = None


class SuggestionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    model: Optional[str] = settings.chat_model


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    session_id: Optional[str] = None


class FileSaveRequest(BaseModel):
    path: Optional[str] = None
    file: Optional[str] = None
    content: str = Field(max_length=5_000_000)


class TerminalExecuteRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2_000)
