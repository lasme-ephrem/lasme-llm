from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Request

from core.config import settings


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
PROXY_HEADERS = (
    "cf-connecting-ip",
    "x-forwarded-for",
    "x-real-ip",
    "cf-ray",
)
INSECURE_ACCESS_TOKENS = {
    "replace-with-a-long-random-token",
    "change-me",
    "changeme",
    "your-token",
    "votre-jeton",
}


class SecurityError(ValueError):
    """Raised when an operation escapes the application's trust boundary."""


def is_proxied_request(request: Request) -> bool:
    return any(request.headers.get(header) for header in PROXY_HEADERS)


def is_direct_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in LOCAL_HOSTS and not is_proxied_request(request)


def configured_access_token() -> str:
    token = settings.access_token.strip()
    if (
        len(token) < 24
        or token.casefold() in INSECURE_ACCESS_TOKENS
        or "replace-with" in token.casefold()
    ):
        return ""
    return token


def request_has_valid_token(request: Request) -> bool:
    configured = configured_access_token()
    if not configured:
        return False
    supplied = request.headers.get("x-lasme-token", "").strip()
    if not supplied:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
    if not supplied:
        supplied = request.cookies.get("lasme_access_token", "").strip()
    if not supplied:
        supplied = request.query_params.get("token", "").strip()
    return bool(supplied) and secrets.compare_digest(supplied, configured)


def request_has_valid_query_token(request: Request) -> bool:
    configured = configured_access_token()
    supplied = request.query_params.get("token", "").strip()
    return (
        bool(configured)
        and bool(supplied)
        and secrets.compare_digest(supplied, configured)
    )


def resolve_workspace_path(path: str | Path = ".") -> Path:
    root = settings.workspace_root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SecurityError(
            f"Path outside the configured workspace is not allowed: {path}"
        ) from exc
    return resolved
