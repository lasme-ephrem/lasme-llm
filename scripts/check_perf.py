"""Performance regression gate: tok/s vs Phase 0 baselines (−10% budget).

Measures generation throughput on the live router for one profile and
fails when the best of N runs drops more than 10% below the stored
baseline. Baselines live in .models/logs/perf_baseline.json and were
seeded from Phase 0 measurements on the reference RTX 4070 Ti SUPER.

Usage:
  python -m scripts.check_perf --model gemma-4-e4b
  python -m scripts.check_perf --model gemma-4-12b --update-baseline
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

from core.config import settings

BASELINE_PATH = (
    Path(__file__).resolve().parent.parent / ".models" / "logs" / "perf_baseline.json"
)
DEFAULT_BASELINES = {  # Phase 0 measured, MTP n=4
    "gemma-4-12b": 211.0,
    "gemma-4-e4b": 129.0,
    "gemma-4-e2b": 214.0,
}
TOLERANCE = 0.10

GEN_PROMPT = (
    "Raconte une histoire détaillée et continue sans t'arrêter. "
    "Sujet : un phare qui voit passer les siècles. "
)


def load_baselines() -> dict:
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return dict(DEFAULT_BASELINES)


def measure_tok_s(base_url: str, model: str, runs: int) -> float:
    """Median throughput over N runs at temperature 0.

    Greedy decoding keeps the MTP drafter's acceptance rate stable
    (a temperature-0.7 story prompt made acceptance swing 16-94 %
    between runs, masking real throughput by ±30 %).
    """
    values = []
    with httpx.Client(base_url=base_url, timeout=300) as client:
        # Échauffement non chronométré : après une bascule de modèle du
        # routeur, le premier prompt paie le chargement des poids et le
        # réchauffage du draft MTP, ce qui empoisonnait la médiane.
        client.post(
            "/completion",
            json={
                "model": model,
                "prompt": GEN_PROMPT,
                "n_predict": 8,
                "temperature": 0.0,
                "cache_prompt": True,
            },
        )
        for _ in range(runs):
            response = client.post(
                "/completion",
                json={
                    "model": model,
                    "prompt": GEN_PROMPT,
                    "n_predict": 256,
                    "temperature": 0.0,
                    "cache_prompt": True,
                },
            )
            response.raise_for_status()
            values.append(response.json()["timings"]["predicted_per_second"])
    return round(statistics.median(values), 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--base", default=settings.llama_base_url)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Écris la mesure courante comme nouvelle référence.",
    )
    args = parser.parse_args()

    baselines = load_baselines()
    measured = measure_tok_s(args.base, args.model, args.runs)

    if args.update_baseline:
        baselines[args.model] = measured
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(baselines, indent=2), encoding="utf-8"
        )
        print(f"baseline {args.model} -> {measured} tok/s ({BASELINE_PATH})")
        return

    baseline = baselines.get(args.model)
    if baseline is None:
        print(f"aucune baseline pour {args.model} ; mesure = {measured} tok/s")
        print("relancez avec --update-baseline pour en créer une")
        return

    floor = baseline * (1 - TOLERANCE)
    status = "OK" if measured >= floor else "RÉGRESSION"
    print(
        f"{args.model}: {measured} tok/s "
        f"(baseline {baseline}, plancher {round(floor, 1)}) -> {status}"
    )
    if measured < floor:
        raise SystemExit(
            f"RÉGRESSION PERFORMANCE: {measured} < {round(floor, 1)} tok/s "
            f"(-{TOLERANCE:.0%} de la baseline {baseline})"
        )


if __name__ == "__main__":
    main()
