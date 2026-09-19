import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    app_name: str = "Lasme LLM"
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # llama.cpp runtime (v2). The supervisor launches llama-server in
    # router mode from these settings; the client talks OpenAI-compatible
    # HTTP to llama_base_url.
    llama_server_path: str = os.getenv("LLAMA_SERVER_PATH", "")
    llama_base_url: str = os.getenv(
        "LLAMA_BASE_URL",
        "http://"
        + os.getenv("LLAMA_HOST", "127.0.0.1")
        + ":"
        + os.getenv("LLAMA_PORT", "8080"),
    )
    llama_host: str = os.getenv("LLAMA_HOST", "127.0.0.1")
    llama_port: int = int(os.getenv("LLAMA_PORT", "8080"))
    llama_models_max: int = int(os.getenv("LLAMA_MODELS_MAX", "2"))
    llama_startup_timeout: int = int(os.getenv("LLAMA_STARTUP_TIMEOUT", "120"))
    hf_cache_dir: str = os.getenv("HF_HOME", "")

    # Search Engine Configuration
    perplexity_api_key: str = os.getenv("PERPLEXITY_API_KEY", "")
    perplexity_sonar_model: str = os.getenv("PERPLEXITY_SONAR_MODEL", "sonar")
    brave_search_api_key: str = os.getenv("BRAVE_SEARCH_API_KEY", "")
    searxng_enabled: bool = _env_bool("SEARXNG_ENABLED", False)
    searxng_base_url: str = os.getenv(
        "SEARXNG_BASE_URL",
        "http://127.0.0.1:8080",
    ).rstrip("/")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    openalex_api_key: str = os.getenv("OPENALEX_API_KEY", "")
    # Monid (tinyfish gateway) : premier provider de la chaîne de recherche
    # web. Optionnel — sans clé, Monid est simplement absent de la chaîne.
    monid_api_key: str = os.getenv("MONID_API_KEY", "")
    monid_max_price_usd: float = float(os.getenv("MONID_MAX_PRICE_USD", "0.01"))
    monid_timeout_s: int = int(os.getenv("MONID_TIMEOUT_S", "30"))
    search_specialists_enabled: bool = _env_bool(
        "SEARCH_SPECIALISTS_ENABLED",
        True,
    )

    # Preferred models (v2): profile ids served by the llama.cpp router.
    # Vision is native on Gemma 4 (mmproj), so the quality profile covers
    # chat, coding, reasoning and vision; E4B is the fast lane.
    coding_model: str = os.getenv("CODING_MODEL", "gemma-4-12b")
    chat_model: str = os.getenv("CHAT_MODEL", "gemma-4-12b")
    reasoning_model: str = os.getenv("REASONING_MODEL", "gemma-4-12b")
    fast_model: str = os.getenv("FAST_MODEL", "gemma-4-e4b")
    vision_model: str = os.getenv("VISION_MODEL", "gemma-4-12b")
    # Additional models selectable in the UI without being defaults.
    extra_models: list[str] = [
        m.strip()
        for m in os.getenv("EXTRA_MODELS", "").split(",")
        if m.strip()
    ]

    # Inference defaults
    temperature: float = 0.2
    max_tokens: int = 4096

    # Local security. Proxied requests (Cloudflared, reverse proxies) require
    # LASME_ACCESS_TOKEN. Coding routes remain local-only unless explicitly
    # enabled in addition to supplying the token.
    access_token: str = os.getenv("LASME_ACCESS_TOKEN", "")
    allow_remote_coding: bool = _env_bool("LASME_ALLOW_REMOTE_CODING", False)
    allow_destructive_agent_tools: bool = _env_bool(
        "LASME_ALLOW_DESTRUCTIVE_AGENT_TOOLS",
        False,
    )
    agent_terminal_enabled: bool = _env_bool(
        "LASME_ENABLE_AGENT_TERMINAL",
        False,
    )
    workspace_root: Path = Path(
        os.getenv(
            "LASME_WORKSPACE_ROOT",
            str(Path(__file__).resolve().parent.parent),
        )
    ).resolve()
    allowed_commands: str = os.getenv(
        "LASME_ALLOWED_COMMANDS",
        "",
    )
    max_upload_bytes: int = int(
        os.getenv("LASME_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    )
    external_image_generation_enabled: bool = _env_bool(
        "LASME_ENABLE_EXTERNAL_IMAGE_GENERATION",
        True,
    )
    public_base_url: str = os.getenv("LASME_PUBLIC_BASE_URL", "").rstrip("/")

settings = Settings()
