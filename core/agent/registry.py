"""Composition of the full agent tool registry."""

from __future__ import annotations

from typing import Any, Optional

from core.agent.builtin import build_default_registry
from core.agent.tools import ToolRegistry
from core.agent.tools_mcp_stack import register_mcp_stack
from core.agent.tools_platform import register_platform_tools
from core.agent.tools_web import register_web_tools


def build_agent_registry(
    *,
    mcp_client: Optional[Any] = None,
    web_enabled: bool = True,
    model_id: str = "gemma-4-12b",
    rag_search_fn: Optional[Any] = None,
    python_runner: Optional[Any] = None,
    file_store: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    vision_model: str = "gemma-4-12b",
    prebound_image: Optional[str] = None,
    artifact_store: Optional[Any] = None,
    default_project_id: str = "default",
) -> ToolRegistry:
    """Builtin tools, optional web tools, platform tools, then the MCP stack.

    ``web_research`` / ``web_read`` are registered only when ``web_enabled``
    is true. ``model_id`` selects which MCP servers the stack exposes.
    """
    registry = build_default_registry()

    if web_enabled:
        register_web_tools(registry, mcp_client=mcp_client)

    register_platform_tools(
        registry,
        rag_search_fn=rag_search_fn,
        python_runner=python_runner,
        file_store=file_store,
        vision_client=vision_client,
        vision_model=vision_model,
        prebound_image=prebound_image,
        artifact_store=artifact_store,
        default_project_id=default_project_id,
    )
    register_mcp_stack(
        registry,
        mcp_client=mcp_client,
        model_id=model_id,
    )
    return registry
