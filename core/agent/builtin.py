"""Built-in agent tools always available to every run.

Phase 2 ships the agentic plumbing with a small, dependency-free toolset
(time, calculator, echo) so the loop can be exercised and tested end to
end; Phase 3 replaces the heavyweight prompt-era integrations (web
search, RAG, python runner, files, canvas) by registry entries.
"""

from __future__ import annotations

import ast
import datetime
import operator
from typing import Any, Dict

from core.agent.tools import (
    CATEGORY_EXEC,
    CATEGORY_READ,
    ToolDefinition,
    ToolRegistry,
)

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.expr) -> float:
    """Evaluate an arithmetic AST — no names, no calls, no attributes."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("expression arithmétique non supportée")


async def _calculate(args: Dict[str, Any]) -> str:
    tree = ast.parse(str(args["expression"]), mode="eval")
    return str(_safe_eval(tree.body))


async def _current_time(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "timezone": datetime.datetime.now().astimezone().tzname(),
        "weekday": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][now.weekday()],
    }


async def _echo(args: Dict[str, Any]) -> str:
    return str(args.get("text", ""))


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="calculate",
            description=(
                "Calcule une expression arithétique (+, -, *, /, //, %, **). "
                "À utiliser pour toute opération numérique exacte."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "L'expression, ex: (2+3)*7/4",
                    }
                },
                "required": ["expression"],
            },
            handler=_calculate,
            category=CATEGORY_EXEC,
            timeout_s=5.0,
        )
    )
    registry.register(
        ToolDefinition(
            name="current_time",
            description="Date et heure locales actuelles, avec fuseau et jour de la semaine.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_current_time,
            category=CATEGORY_READ,
            timeout_s=5.0,
        )
    )
    registry.register(
        ToolDefinition(
            name="echo",
            description="Renvoie le texte tel quel — outil de diagnostic.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo,
            category=CATEGORY_READ,
            timeout_s=5.0,
        )
    )
    return registry
