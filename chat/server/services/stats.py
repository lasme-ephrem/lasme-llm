"""Statistiques de génération (tok/s, TTFT) — métadonnées persistées.

Extrait de ``chat/server/main.py`` (refonte modulaire).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


def build_generation_stats(
    chunk: Dict[str, Any],
    *,
    model: str,
    started_at: float,
    first_content_at: Optional[float],
) -> Dict[str, Any]:
    """Normalize provider timings into compact, persisted message metadata."""
    eval_count = int(chunk.get("eval_count") or 0)
    prompt_count = int(chunk.get("prompt_eval_count") or 0)
    eval_duration_ns = int(chunk.get("eval_duration") or 0)
    total_duration_ns = int(chunk.get("total_duration") or 0)
    load_duration_ns = int(chunk.get("load_duration") or 0)
    prompt_duration_ns = int(chunk.get("prompt_eval_duration") or 0)
    measured_total = max(0.0, time.monotonic() - started_at)

    def seconds(nanoseconds: int) -> Optional[float]:
        if nanoseconds <= 0:
            return None
        return round(nanoseconds / 1_000_000_000, 2)

    reported_total = (
        total_duration_ns / 1_000_000_000
        if total_duration_ns > 0
        else 0.0
    )
    stats: Dict[str, Any] = {
        "model": model,
        "prompt_tokens": prompt_count,
        "output_tokens": eval_count,
        "tokens_per_second": (
            round(eval_count / (eval_duration_ns / 1_000_000_000), 1)
            if eval_count and eval_duration_ns
            else None
        ),
        "generation_seconds": seconds(eval_duration_ns),
        # Prefer the user-perceived wall time when transport and scheduling
        # make it slightly longer than the provider's internal total_duration.
        "total_seconds": round(max(reported_total, measured_total), 2),
        "time_to_first_token": (
            round(max(0.0, first_content_at - started_at), 2)
            if first_content_at is not None
            else None
        ),
        "load_seconds": seconds(load_duration_ns),
        "prompt_seconds": seconds(prompt_duration_ns),
        "done_reason": chunk.get("done_reason"),
    }
    return {
        key: value
        for key, value in stats.items()
        if value is not None and value != ""
    }
