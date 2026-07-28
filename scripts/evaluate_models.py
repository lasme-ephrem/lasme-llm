r"""Reproducible Ollama benchmark for the Lasme model roster.

Examples:
    .\.venv\Scripts\python.exe -m scripts.evaluate_models
    .\.venv\Scripts\python.exe -m scripts.evaluate_models --output .runtime\model-benchmark.json
    .\.venv\Scripts\python.exe -m scripts.evaluate_models --models lasme-smol-fast lasme-qwen-vision
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from core.config import settings
from core.inference.client import LasmeLLMClient


CASES = [
    {
        "name": "french_explanation",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Explique en quatre phrases pourquoi le ciel paraît bleu, "
                    "avec une formule courte et une conclusion."
                ),
            }
        ],
    },
    {
        "name": "context_follow_up",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Je dispose de 16 Go de VRAM et je privilégie les modèles GGUF."
                ),
            },
            {
                "role": "assistant",
                "content": "Je tiendrai compte de ces deux contraintes.",
            },
            {
                "role": "user",
                "content": (
                    "Laquelle limite le plus un très long contexte, et pourquoi ?"
                ),
            },
        ],
    },
    {
        "name": "reasoning",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Un service possède 99,9 % de disponibilité mensuelle. "
                    "Calcule le temps d’arrêt maximal sur 30 jours, montre le "
                    "calcul puis vérifie le résultat."
                ),
            }
        ],
    },
    {
        "name": "coding",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Écris une fonction Python qui vérifie qu’un chemin résolu "
                    "reste dans un dossier racine. Réponds avec le code et deux tests."
                ),
            }
        ],
    },
]


def _seconds(nanoseconds: Any) -> float:
    try:
        return max(0.0, float(nanoseconds or 0) / 1_000_000_000)
    except (TypeError, ValueError):
        return 0.0


def response_metrics(
    response: dict[str, Any],
    *,
    wall_seconds: float,
) -> dict[str, Any]:
    output_tokens = int(response.get("eval_count") or 0)
    prompt_tokens = int(response.get("prompt_eval_count") or 0)
    generation_seconds = _seconds(response.get("eval_duration"))
    prompt_seconds = _seconds(response.get("prompt_eval_duration"))
    load_seconds = _seconds(response.get("load_duration"))
    answer = str((response.get("message") or {}).get("content") or "").strip()
    thinking = str((response.get("message") or {}).get("thinking") or "").strip()
    return {
        "wall_seconds": round(max(0.0, wall_seconds), 3),
        "load_seconds": round(load_seconds, 3),
        "prompt_seconds": round(prompt_seconds, 3),
        "generation_seconds": round(generation_seconds, 3),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "tokens_per_second": (
            round(output_tokens / generation_seconds, 2)
            if output_tokens and generation_seconds
            else 0.0
        ),
        "answer_chars": len(answer),
        "thinking_chars": len(thinking),
        "answer_preview": answer[:280],
        "done_reason": response.get("done_reason"),
        "valid_answer": bool(answer),
    }


def summarize_model(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    output_tokens = sum(int(row.get("output_tokens") or 0) for row in rows)
    generation_seconds = sum(
        float(row.get("generation_seconds") or 0) for row in rows
    )
    speeds = [
        float(row["tokens_per_second"])
        for row in rows
        if float(row.get("tokens_per_second") or 0) > 0
    ]
    return {
        "cases": len(rows),
        "valid_answers": sum(bool(row.get("valid_answer")) for row in rows),
        "output_tokens": output_tokens,
        "weighted_tokens_per_second": (
            round(output_tokens / generation_seconds, 2)
            if output_tokens and generation_seconds
            else 0.0
        ),
        "median_tokens_per_second": (
            round(statistics.median(speeds), 2) if speeds else 0.0
        ),
        "average_wall_seconds": (
            round(
                statistics.mean(
                    float(row.get("wall_seconds") or 0) for row in rows
                ),
                3,
            )
            if rows
            else 0.0
        ),
        "max_load_seconds": round(
            max((float(row.get("load_seconds") or 0) for row in rows), default=0),
            3,
        ),
    }


async def evaluate_model(
    client: LasmeLLMClient,
    model: str,
    *,
    num_predict: int,
    num_ctx: int,
) -> dict[str, Any]:
    available = {
        str(item.get("name") or "").removesuffix(":latest")
        for item in await client.list_models()
    }
    normalized = model.removesuffix(":latest")
    if normalized not in available:
        return {
            "model": model,
            "status": "missing",
            "summary": summarize_model([]),
            "results": [],
        }

    results: list[dict[str, Any]] = []
    for case in CASES:
        started = time.perf_counter()
        response = await client.chat(
            model=model,
            messages=case["messages"],
            temperature=0.2,
            think=False,
            num_ctx=num_ctx,
            num_predict=num_predict,
        )
        metrics = response_metrics(
            response,
            wall_seconds=time.perf_counter() - started,
        )
        results.append({"case": case["name"], **metrics})
    return {
        "model": model,
        "status": "ok",
        "summary": summarize_model(results),
        "results": results,
    }


def default_models() -> list[str]:
    return list(
        dict.fromkeys(
            [
                settings.chat_model,
                settings.fast_model,
                settings.vision_model,
            ]
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the resident Gemma baseline and the two fast Lasme models."
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=default_models(),
        help="Ollama model names to benchmark.",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=384,
        help="Maximum generated tokens per case (64-2048).",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=8_192,
        help="Context used by the benchmark (2048-65536).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Parent directory must already exist.",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    num_predict = max(64, min(int(args.num_predict), 2_048))
    num_ctx = max(2_048, min(int(args.num_ctx), 65_536))
    benchmark_started = time.perf_counter()
    client = LasmeLLMClient()
    try:
        models = []
        for model in args.models:
            models.append(
                await evaluate_model(
                    client,
                    model,
                    num_predict=num_predict,
                    num_ctx=num_ctx,
                )
            )
    finally:
        await client.aclose()
    return {
        "benchmark": "lasme-local-models-v1",
        "ollama_base_url": settings.ollama_base_url,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "elapsed_seconds": round(time.perf_counter() - benchmark_started, 3),
        "models": models,
    }


async def main() -> None:
    args = parse_args()
    report = await run(args)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(payload)
    if args.output:
        output = args.output.resolve()
        if not output.parent.is_dir():
            raise SystemExit(f"Output directory does not exist: {output.parent}")
        output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
