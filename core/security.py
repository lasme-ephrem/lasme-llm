from __future__ import annotations

import ipaddress
import secrets
import socket
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from fastapi import Request

from core.config import settings


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
PROXY_HEADERS = (
    "cf-connecting-ip",
    "x-forwarded-for",
    "x-real-ip",
    "cf-ray",
)


class SecurityError(ValueError):
    """Raised when an operation escapes the application's trust boundary."""


def is_proxied_request(request: Request) -> bool:
    return any(request.headers.get(header) for header in PROXY_HEADERS)


def is_direct_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in LOCAL_HOSTS and not is_proxied_request(request)


def request_has_valid_token(request: Request) -> bool:
    configured = settings.access_token.strip()
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
    configured = settings.access_token.strip()
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


def _validate_ip_addresses(addresses: Iterable[str]) -> None:
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SecurityError(f"Private or reserved network address blocked: {ip}")


def validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError("Only http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise SecurityError("URL hostname is missing.")
    if parsed.username or parsed.password:
        raise SecurityError("URLs containing credentials are not allowed.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in LOCAL_HOSTS or hostname.endswith(".local"):
        raise SecurityError("Local network URLs are not allowed.")

    try:
        _validate_ip_addresses([hostname])
    except ValueError:
        try:
            infos = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise SecurityError(f"Unable to resolve URL hostname: {hostname}") from exc
        _validate_ip_addresses({info[4][0] for info in infos})

    return url
