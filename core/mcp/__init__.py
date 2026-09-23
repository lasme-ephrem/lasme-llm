"""Client MCP de Lasme LLM.

Le pool stdio et le catalogue vivent dans ``pool`` et ``catalog``.
Ce paquet ne lance aucun serveur à l'import.
"""

from __future__ import annotations

import importlib
from typing import Any

from core.mcp.types import (
    McpCallResult,
    McpClient,
    McpServerSpec,
    ScriptedMcpClient,
)

__all__ = [
    "McpCallResult",
    "McpClient",
    "McpServerSpec",
    "ScriptedMcpClient",
    "StdioMcpPool",
    "build_catalog",
    "configured_server_ids",
    "get_mcp_client",
    "reset_mcp_client_for_tests",
]

_LAZY = {
    "build_catalog": ("core.mcp.catalog", "build_catalog"),
    "configured_server_ids": ("core.mcp.catalog", "configured_server_ids"),
    "StdioMcpPool": ("core.mcp.pool", "StdioMcpPool"),
    "get_mcp_client": ("core.mcp.pool", "get_mcp_client"),
    "reset_mcp_client_for_tests": ("core.mcp.pool", "reset_mcp_client_for_tests"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr)
    globals()[name] = value
    return value
