import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

# uvicorn ne configure que ses propres loggers : sans ceci, les traces INFO de
# l'app restent invisibles. basicConfig est un no-op si un handler existe déjà.
logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    app_name: str = "Lasme LLM"

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
        False,
    )
    public_base_url: str = os.getenv("LASME_PUBLIC_BASE_URL", "").rstrip("/")

settings = Settings()
