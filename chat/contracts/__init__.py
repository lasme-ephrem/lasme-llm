"""Contrats d'API Lasme LLM : schémas Pydantic et catalogue de modèles.

Une seule source de vérité pour les requêtes/réponses HTTP — les modules
de routes n'inventent pas leurs propres modèles.
"""

from chat.contracts.schemas import (  # noqa: F401
    AgentRunRequest,
    ArtifactCreateRequest,
    ArtifactPreviewRequest,
    ArtifactUpdateRequest,
    BranchRequest,
    ChatMessage,
    ChatRequest,
    DeepResearchRequest,
    FileSaveRequest,
    ImageGenerateRequest,
    MemoryCreateRequest,
    MemorySettingsRequest,
    MemoryUpdateRequest,
    MessageEditRequest,
    MessageUpdateRequest,
    ProjectCreateRequest,
    ProjectFileUpdateRequest,
    ProjectUpdateRequest,
    PythonRunRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
    SuggestionRequest,
    TerminalExecuteRequest,
    allowed_model_names,
    is_model_available,
    model_key,
    validate_model_name,
)
