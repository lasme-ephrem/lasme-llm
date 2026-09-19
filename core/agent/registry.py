"""Composition of the full agent tool registry."""

from __future__ import annotations

from typing import Any, Callable, Optional

from core.agent.builtin import build_default_registry
from core.agent.tools import ToolRegistry
from core.agent.tools_platform import register_platform_tools
from core.agent.tools_web import register_web_tools


def build_agent_registry(
    *,
    search_fn: Optional[Callable[..., Any]] = None,
    fetch_fn: Optional[Callable[[str], str]] = None,
    rag_search_fn: Optional[Any] = None,
    python_runner: Optional[Any] = None,
    file_store: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    vision_model: str = "gemma-4-12b",
) -> ToolRegistry:
    """Builtin tools + web + platform tools, with injectable engines.

    ``search_fn``/``fetch_fn`` default to the proven v1 chain; a tinyfish
    (Monid) engine can be injected later without touching contracts.
    """
    registry = build_default_registry()

    if search_fn is not None and fetch_fn is not None:
        register_web_tools(registry, search_fn=search_fn, fetch_fn=fetch_fn)

    register_platform_tools(
        registry,
        rag_search_fn=rag_search_fn,
        python_runner=python_runner,
        file_store=file_store,
        vision_client=vision_client,
        vision_model=vision_model,
    )
    return registry
