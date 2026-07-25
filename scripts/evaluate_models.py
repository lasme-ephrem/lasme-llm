r"""Small repeatable smoke benchmark for the two local Ollama models.

Usage:
    .\.venv\Scripts\python.exe -m scripts.evaluate_models
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from core.config import settings
from core.inference.client import LasmeLLMClient


CASES = [
    {
        "name": "concise_french",
        "messages": [
            {
                "role": "user",
                "content": "Explique en trois phrases pourquoi le ciel paraît bleu.",
            }
        ],
    },
    {
        "name": "conversation_follow_up",
        "messages": [
            {
                "role": "user",
                "content": "Je préfère les modèles GGUF et je dispose de 16 Go de VRAM.",
            },
            {
                "role": "assistant",
                "content": "Compris, je garderai ces deux contraintes en tête.",
            },
            {
                "role": "user",
                "content": "Lequel de ces deux critères limite le plus un contexte très long ?",
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
                    "Calcule le temps d’arrêt maximal sur 30 jours et vérifie ton calcul."
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
                    "Écris une fonction Python sûre qui vérifie qu’un chemin résolu "
                    "reste dans un dossier racine. Réponds avec le code et deux tests."
                ),
            }
        ],
    },
]


async def evaluate_model(client: LasmeLLMClient, model: str) -> list[dict[str, Any]]:
    results = []
    for case in CASES:
        started = time.perf_counter()
        response = await client.chat(
            model=model,
            messages=case["messages"],
            temperature=1.0,
            think=True,
            num_ctx=16_384,
            num_predict=1_024,
        )
        elapsed = round(time.perf_counter() - started, 2)
        message = response.get("message", {})
        results.append(
            {
                "model": model,
                "case": case["name"],
                "seconds": elapsed,
                "answer_chars": len(message.get("content", "")),
                "thinking_chars": len(message.get("thinking", "")),
                "answer_preview": message.get("content", "")[:240],
            }
        )
    return results


async def main() -> None:
    client = LasmeLLMClient()
    try:
        all_results = []
        for model in (settings.chat_model, settings.coding_model):
            all_results.extend(await evaluate_model(client, model))
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
