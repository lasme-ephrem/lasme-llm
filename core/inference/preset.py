"""Generation of the llama-server router preset (INI) from profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from core.inference.profiles import RuntimeProfile

GLOBAL_KEYS = {
    "jinja": True,
    "n-gpu-layers": 999,
    "flash-attn": "on",
    "metrics": True,
    # NOTE: "dedup-cache-models" exists in newer llama.cpp releases but is
    # rejected by builds around b10358; auto-discovered cache entries are
    # filtered client-side in LasmeLLMClient.list_models instead.
}


def _render_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_preset(profiles: Iterable[RuntimeProfile]) -> str:
    """Render the router INI for the given runtime profiles."""
    lines = ["version = 1", "", "[*]"]
    lines += [f"{key} = {_render_value(value)}" for key, value in GLOBAL_KEYS.items()]
    for profile in profiles:
        lines += ["", f"[{profile.id}]"]
        lines += [
            f"{key} = {_render_value(value)}"
            for key, value in profile.preset_section().items()
        ]
    lines.append("")
    return "\n".join(lines)


def write_preset(path: Path, profiles: Iterable[RuntimeProfile]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_preset(profiles), encoding="utf-8")
    return path
