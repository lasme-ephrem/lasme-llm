"""Tool registry with strict schema validation — the anti-failure layer.

Phase 0 measured that Gemma 4 emits well-formed tool calls as long as the
orchestrator (a) gives the model enough token budget and (b) never trusts
the output blindly. This module owns the "never trust" half:

- JSON arguments are parsed and validated against the declared schema
  (required properties + primitive type checking — a deliberate JSON
  Schema subset, no external dependency);
- execution is bounded (timeout, output truncation);
- every failure mode is a structured ``ToolResult`` the orchestrator can
  feed back to the model for a bounded number of repair attempts.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_OUTPUT_CHARS = 8_000

# Categories let policies (and the UI) distinguish reading from acting.
CATEGORY_READ = "read"
CATEGORY_WRITE = "write"
CATEGORY_EXEC = "exec"
CATEGORY_NETWORK = "network"

INVALID_JSON = "invalid_json"
SCHEMA_VIOLATION = "schema_violation"
UNKNOWN_TOOL = "unknown_tool"
TIMEOUT = "timeout"
EXECUTION_ERROR = "execution_error"

_TYPE_CHECKS = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def for_model(self) -> str:
        """Compact representation injected back into the conversation."""
        if self.ok:
            return self.output
        return (
            f"Tool error ({self.error_code}): {self.error}. "
            "Fix the arguments and call the tool again, or proceed without it."
        )


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Awaitable[Any]]
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    category: str = CATEGORY_READ

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n…[sortie tronquée à {limit} caractères]", True


class ToolValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_arguments(
    arguments: Dict[str, Any], schema: Dict[str, Any]
) -> None:
    """Validate a JSON Schema subset: required + property types + enums."""
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in arguments or arguments[name] in ("", None):
            raise ToolValidationError(
                SCHEMA_VIOLATION, f"missing required property '{name}'"
            )
    for name, value in arguments.items():
        declaration = properties.get(name)
        if declaration is None:
            # Undeclared extras are tolerated: models add harmless keys,
            # and the schema subset here is intentionally minimal.
            continue
        expected = declaration.get("type")
        check = _TYPE_CHECKS.get(expected)
        if check and not isinstance(value, check):
            raise ToolValidationError(
                SCHEMA_VIOLATION,
                f"property '{name}' must be of type {expected}, "
                f"got {type(value).__name__}",
            )
        enum = declaration.get("enum")
        if enum and value not in enum:
            raise ToolValidationError(
                SCHEMA_VIOLATION,
                f"property '{name}' must be one of {enum}",
            )
        if expected == "integer" and isinstance(value, bool):
            raise ToolValidationError(
                SCHEMA_VIOLATION, f"property '{name}' must be an integer"
            )


class ToolRegistry:
    """Declarative registry; one instance per agent configuration."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not tool.name or not tool.name.replace("_", "").isalnum():
            raise ValueError(f"invalid tool name: {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def to_openai(self) -> List[Dict[str, Any]]:
        return [tool.to_openai() for tool in self._tools.values()]

    async def execute(self, name: str, arguments_json: str) -> ToolResult:
        """Validate then run a tool call, always within limits."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"unknown tool '{name}'; available: {', '.join(self.names())}",
                error_code=UNKNOWN_TOOL,
            )
        started = time.monotonic()
        try:
            arguments = (
                json.loads(arguments_json)
                if isinstance(arguments_json, str)
                else dict(arguments_json or {})
            )
            if not isinstance(arguments, dict):
                raise ToolValidationError(
                    INVALID_JSON, "arguments must be a JSON object"
                )
        except (json.JSONDecodeError, TypeError) as exc:
            return ToolResult(
                ok=False,
                error=f"arguments are not valid JSON: {exc}",
                error_code=INVALID_JSON,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except ToolValidationError as exc:
            return ToolResult(
                ok=False,
                error=str(exc),
                error_code=INVALID_JSON,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            validate_arguments(arguments, tool.parameters)
        except ToolValidationError as exc:
            return ToolResult(
                ok=False,
                error=str(exc),
                error_code=exc.code,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            raw = await asyncio.wait_for(
                tool.handler(arguments), timeout=tool.timeout_s
            )
        except asyncio.TimeoutError:
            return ToolResult(
                ok=False,
                error=f"tool exceeded its {tool.timeout_s}s timeout",
                error_code=TIMEOUT,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # tool bugs must not kill the run
            return ToolResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                error_code=EXECUTION_ERROR,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if isinstance(raw, ToolResult):
            output, truncated = _truncate(raw.output, tool.max_output_chars)
            meta = dict(raw.meta or {})
            meta["truncated"] = truncated
            return ToolResult(
                ok=raw.ok,
                output=output,
                error=raw.error,
                error_code=raw.error_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                meta=meta,
            )

        output = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        output, truncated = _truncate(output, tool.max_output_chars)
        return ToolResult(
            ok=True,
            output=output,
            duration_ms=int((time.monotonic() - started) * 1000),
            meta={"truncated": truncated},
        )
