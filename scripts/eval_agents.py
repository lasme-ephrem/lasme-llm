"""Automated agent evals against the live llama.cpp runtime.

Replays a battery of missions through the real orchestrator + builtin
tools and scores: task success, tool-call formation (valid JSON args),
turn efficiency, wall time. Writes JSON + prints a table.

Usage:
  python -m scripts.eval_agents --model gemma-4-e4b
  python -m scripts.eval_agents --model gemma-4-12b --min-success 0.8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path

from core.agent.builtin import build_default_registry
from core.agent.orchestrator import AgentConfig, AgentOrchestrator
from core.config import settings
from core.inference.client import LasmeLLMClient

RESULTS_PATH = (
    Path(__file__).resolve().parent.parent / ".models" / "logs" / "agent_evals.json"
)

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _has_time(text: str) -> bool:
    return bool(re.search(r"\d{1,2}[:h]\d{2}", text)) or any(
        day in text.lower() for day in WEEKDAYS
    )


SCENARIOS = [
    {
        "name": "calc_direct",
        "prompt": "Combien font (17*23)+100 ? Utilise l'outil calculate.",
        "expect": "491",
        "expect_tools": 1,
    },
    {
        "name": "calc_puissance",
        "prompt": "Calcule 2**10 + 24 avec calculate.",
        "expect": "1048",
        "expect_tools": 1,
    },
    {
        "name": "somme_gauss",
        "prompt": (
            "Calcule la somme des entiers de 1 à 100 avec calculate "
            "(écris l'expression arithmétique)."
        ),
        "expect": "5050",
        "expect_tools": 1,
    },
    {
        "name": "heure",
        "prompt": "Quel jour sommes-nous et quelle heure est-il ? Utilise current_time.",
        "check": _has_time,
        "expect_tools": 1,
    },
    {
        "name": "sans_outil",
        "prompt": "Réponds en un seul mot : quelle est la couleur du cheval blanc d'Henri IV ?",
        "expect": "blanc",
        "expect_tools": 0,
    },
    {
        "name": "multi_outils",
        "prompt": (
            "Donne-moi (12*12) et le jour de la semaine actuel. "
            "Utilise les outils nécessaires."
        ),
        "expect": "144",
        "check_extra": _has_time,
        "expect_tools": 2,
    },
    {
        "name": "outil_inexistant",
        "prompt": (
            "Traduit 'bonjour' en anglais. Si l'outil exact n'existe pas, "
            "réponds directement sans inventer d'outil."
        ),
        "expect": "hello",
    },
    {
        "name": "echo_determinisme",
        "prompt": (
            "Utilise l'outil echo avec le texte LASME-OK-42 puis répète "
            "exactement ce qu'il retourne."
        ),
        "expect": "lasme-ok-42",
        "expect_tools": 1,
    },
]


async def run_evals(model: str, max_turns: int) -> list[dict]:
    client = LasmeLLMClient()
    rows = []
    try:
        for scenario in SCENARIOS:
            registry = build_default_registry()
            orchestrator = AgentOrchestrator(
                client,
                registry,
                AgentConfig(
                    model=model,
                    system_prompt=(
                        "Tu es Lasme, un assistant agentique local. "
                        "Utilise les outils quand c'est pertinent, puis réponds."
                    ),
                    max_turns=max_turns,
                ),
            )
            started = time.monotonic()
            result = await orchestrator.run(
                [{"role": "user", "content": scenario["prompt"]}]
            )
            duration = round(time.monotonic() - started, 1)
            final = result.final_text.lower()
            ok = True
            if "expect" in scenario:
                ok = ok and scenario["expect"].lower() in final
            if scenario.get("check"):
                ok = ok and bool(scenario["check"](result.final_text))
            if scenario.get("check_extra"):
                ok = ok and bool(scenario["check_extra"](result.final_text))
            tool_calls = result.log.tool_calls()
            malformed = sum(
                1
                for event in result.log.events
                if event.type == "tool_result"
                and event.payload.get("error_code") in ("invalid_json", "schema_violation")
            )
            rows.append(
                {
                    "scenario": scenario["name"],
                    "ok": bool(ok),
                    "final_excerpt": result.final_text[:120].strip(),
                    "turns": result.turns,
                    "tool_calls": len(tool_calls),
                    "malformed": malformed,
                    "done_reason": result.done_reason,
                    "seconds": duration,
                }
            )
    finally:
        await client.aclose()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=settings.chat_model)
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument("--min-success", type=float, default=0.8)
    args = parser.parse_args()

    rows = asyncio.run(run_evals(args.model, args.max_turns))
    success = sum(1 for row in rows if row["ok"])
    rate = success / len(rows) if rows else 0.0

    print(f"\n== Évals agentiques — modèle {args.model} ==")
    print(f"{'scénario':<16} {'ok':<4} {'tours':<6} {'outils':<7} {'malformés':<10} {'s':<6}")
    for row in rows:
        print(
            f"{row['scenario']:<16} {str(row['ok']):<4} {row['turns']:<6} "
            f"{row['tool_calls']:<7} {row['malformed']:<10} {row['seconds']:<6}"
        )
        print(f"  → {row['final_excerpt'][:100]}")
    print(f"\nSuccès : {success}/{len(rows)} ({rate:.0%})")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(
            {"model": args.model, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "rows": rows, "success_rate": rate},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Résultats : {RESULTS_PATH}")

    if rate < args.min_success:
        raise SystemExit(
            f"TAUX DE SUCCÈS {rate:.0%} < SEUIL {args.min_success:.0%}"
        )


if __name__ == "__main__":
    main()
