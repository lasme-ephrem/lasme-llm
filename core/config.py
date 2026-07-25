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
    app_name: str = "LLM-lasme"
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Search Engine Configuration
    perplexity_api_key: str = os.getenv("PERPLEXITY_API_KEY", "")
    perplexity_sonar_model: str = os.getenv("PERPLEXITY_SONAR_MODEL", "sonar")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    # Preferred models optimized for RTX 4070 Ti SUPER (16 GB VRAM)
    coding_model: str = os.getenv("CODING_MODEL", "gemma-4-fable")
    chat_model: str = os.getenv("CHAT_MODEL", "gemma-4-chat")
    reasoning_model: str = os.getenv("REASONING_MODEL", "gemma-4-fable")
    vision_model: str = os.getenv("VISION_MODEL", "")

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
    workspace_root: Path = Path(
        os.getenv(
            "LASME_WORKSPACE_ROOT",
            str(Path(__file__).resolve().parent.parent),
        )
    ).resolve()
    allowed_commands: str = os.getenv(
        "LASME_ALLOWED_COMMANDS",
        "python,python.exe,node,node.exe,npm,npm.cmd,npx,npx.cmd,"
        "git,git.exe,rg,rg.exe,pytest,pytest.exe,uvicorn,uvicorn.exe",
    )
    max_upload_bytes: int = int(os.getenv("LASME_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
    external_image_generation_enabled: bool = _env_bool(
        "LASME_ENABLE_EXTERNAL_IMAGE_GENERATION",
        True,
    )
    public_base_url: str = os.getenv("LASME_PUBLIC_BASE_URL", "").rstrip("/")

settings = Settings()
