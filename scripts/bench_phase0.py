"""Phase 0 benchmark harness for the Lasme LLM v2 refonte.

Measures against a running llama-server:
  - generation throughput (exact server timings via /completion)
  - TTFT on /v1/chat/completions streaming at several prefix sizes
  - prompt-cache effect (tokens reprocessed on second identical prefix)
  - tool-call reliability (schema validation, categories of failure)
  - a minimal agent loop (tool call -> result -> final answer, no looping)

Usage (from the v2 worktree, with the main project's venv):
  python -m scripts.bench_phase0 gen   --base http://127.0.0.1:8080
  python -m scripts.bench_phase0 ttft  --base http://127.0.0.1:8080
  python -m scripts.bench_phase0 cache --base http://127.0.0.1:8080
  python -m scripts.bench_phase0 tools --base http://127.0.0.1:8080
  python -m scripts.bench_phase0 loop  --base http://127.0.0.1:8080
  python -m scripts.bench_phase0 all   --base http://127.0.0.1:8080

Results are printed as a table and appended as JSON lines to
  .models/logs/bench_results.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

RESULTS_PATH = Path(__file__).resolve().parent.parent / ".models" / "logs" / "bench_results.jsonl"

GEN_PROMPT = (
    "Raconte une histoire détaillée et continue dans un style narratif riche, "
    "sans jamais t'arrêter ni poser de question. Sujet : un cartographe qui "
    "découvre une île qui change de forme chaque nuit. "
)

PREFIX_FILLER = (
    "Notes de recherche du cartographe : la côte ouste mesure douze lieues, "
    "les marées révèlent des ruines bleues, le sable contient un métal inconnu, "
    "les oiseaux évitent le nord de l'île, la boussole y tourne lentement, "
    "les villageois parlent d'une lumière sous l'eau chaque pleine lune. "
)


def _vram_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _save(result: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with RESULTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False) + "\n")


def bench_generation(base: str, n_predict: int = 256, runs: int = 3) -> dict:
    """Exact throughput from server timings on the native endpoint."""
    rows = []
    with httpx.Client(base_url=base, timeout=300) as client:
        for i in range(runs):
            r = client.post("/completion", json={
                "prompt": GEN_PROMPT,
                "n_predict": n_predict,
                "temperature": 0.7,
                "cache_prompt": True,
            })
            r.raise_for_status()
            t = r.json()["timings"]
            rows.append({
                "run": i + 1,
                "prompt_per_second": round(t.get("prompt_per_second", 0), 1),
                "predicted_n": t.get("predicted_n", 0),
                "tok_s": round(t.get("predicted_per_second", 0), 2),
                "gen_ms": round(t.get("predicted_ms", 0)),
            })
    best = max(rows, key=lambda x: x["tok_s"])
    result = {"bench": "generation", "rows": rows, "best_tok_s": best["tok_s"],
              "vram_mib": _vram_mib()}
    _save(result)
    return result


def _filler(tokens_target: int) -> str:
    # ~75 tokens per repetition (measured with the Gemma 4 tokenizer via
    # usage.prompt_tokens); we report the exact value from the API anyway.
    reps = max(1, tokens_target // 75)
    return PREFIX_FILLER * reps


def _ttft_chat(client: httpx.Client, prefix: str, question: str,
               max_tokens: int = 128) -> dict:
    messages = [
        {"role": "system", "content": "Tu es un assistant de recherche.\n" + prefix},
        {"role": "user", "content": question},
    ]
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    # One retry: a request can occasionally fail while a previous
    # generation is still draining on the same slot.
    last_error = ""
    for attempt in range(2):
        t0 = time.perf_counter()
        ttft = None
        completion_tokens = 0
        prompt_tokens = 0
        try:
            with client.stream("POST", "/v1/chat/completions", json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    if chunk.get("usage"):
                        prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                        completion_tokens = chunk["usage"].get("completion_tokens", 0)
                    if ttft is None:
                        choices = chunk.get("choices") or [{}]
                        delta = choices[0].get("delta", {}) or {}
                        # Gemma 4 thinks first: the first visible token is
                        # usually a reasoning_content delta.
                        if (delta.get("content") or delta.get("tool_calls")
                                or delta.get("reasoning_content")):
                            ttft = (time.perf_counter() - t0) * 1000
            total_ms = (time.perf_counter() - t0) * 1000
            return {"ttft_ms": round(ttft or -1), "total_ms": round(total_ms),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens}
        except httpx.HTTPStatusError as exc:
            last_error = exc.response.text[:200]
            time.sleep(2)
    raise RuntimeError(f"chat request failed twice: {last_error}")


def bench_ttft(base: str, sizes=(1000, 8000, 32000), max_tokens=128) -> dict:
    rows = []
    with httpx.Client(base_url=base, timeout=600) as client:
        for size in sizes:
            prefix = _filler(size)
            for attempt in (1, 2):
                m = _ttft_chat(client, prefix,
                               "En une phrase, quel métier exerce le narrateur ?",
                               max_tokens)
                m.update({"prefix_target_tokens": size, "attempt": attempt})
                rows.append(m)
    result = {"bench": "ttft", "rows": rows, "vram_mib": _vram_mib()}
    _save(result)
    return result


def bench_cache(base: str, prefix_tokens: int = 32000) -> dict:
    """Evidence of prompt caching: tokens re-processed on the 2nd call."""
    prefix = _filler(prefix_tokens)
    rows = []
    with httpx.Client(base_url=base, timeout=600) as client:
        for i, question in enumerate((
            "Quel métier exerce le narrateur ?",
            "Quelle couleur ont les ruines mentionnées ?",
        )):
            r = client.post("/completion", json={
                "prompt": prefix + "\nQuestion: " + question + "\nRéponse:",
                "n_predict": 48,
                "temperature": 0,
                "cache_prompt": True,
            })
            r.raise_for_status()
            t = r.json()["timings"]
            rows.append({"call": i + 1, "prompt_n": t.get("prompt_n", 0),
                         "prompt_ms": round(t.get("prompt_ms", 0)),
                         "prompt_per_second": round(t.get("prompt_per_second", 0), 1)})
    result = {"bench": "cache", "prefix_target_tokens": prefix_tokens,
              "rows": rows, "vram_mib": _vram_mib()}
    _save(result)
    return result


# ---------------------------------------------------------------- tool calls

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Météo actuelle d'une ville",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"},
                               "unit": {"type": "string", "enum": ["C", "F"]}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Recherche sur le web et retourne des résultats",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Exécute du code Python dans un bac à sable",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Crée un événement dans l'agenda",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "hour": {"type": "integer"},
                },
                "required": ["title", "date", "hour"],
            },
        },
    },
]

SCENARIOS = [
    ("Quelle est la météo à Lyon aujourd'hui ?", "get_weather", {"city"}),
    ("Il fait combien de degrés à Tokyo en Fahrenheit ?", "get_weather", {"city"}),
    ("Cherche-moi le prix actuel de la RTX 5090", "search_web", {"query"}),
    ("Calcule la factorielle de 20 avec Python", "run_python", {"code"}),
    ("Crée un rendez-vous dentiste le 2026-10-03 à 14h", "create_event",
     {"title", "date", "hour"}),
    ("Météo à Marseille et à Lille, compare les deux", "get_weather", {"city"}),
    ("Trouve les dernières news sur l'inflation en zone euro", "search_web",
     {"query"}),
    ("Exécute ce calcul : somme des nombres premiers sous 1000", "run_python",
     {"code"}),
    ("Mets un rappel 'payer le loyer' le 1er novembre à 9h", "create_event",
     {"title", "date", "hour"}),
    ("Quel temps fera-t-il à Montréal demain ?", "search_web", {"query"}),
    ("Recherche qui a gagné la dernière coupe du monde de rugby", "search_web",
     {"query"}),
    ("Écris un script Python qui trie une liste de dictionnaires par clé 'age'",
     "run_python", {"code"}),
]


def _validate_tool_call(message: dict, expected: str, required: set) -> str:
    calls = message.get("tool_calls") or []
    if not calls:
        return "no_tool"
    call = calls[0]
    if call.get("name") != expected and call.get("function", {}).get("name") != expected:
        return "wrong_tool"
    raw = call.get("arguments") or call.get("function", {}).get("arguments") or ""
    try:
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "bad_json"
    missing = {k for k in required if k not in args or args[k] in ("", None)}
    if missing:
        return "schema_violation"
    return "ok"


def bench_tools(base: str, runs_per_scenario: int = 1) -> dict:
    rows, cats = [], {}
    with httpx.Client(base_url=base, timeout=180) as client:
        for prompt, expected, required in SCENARIOS:
            for run in range(runs_per_scenario):
                r = client.post("/v1/chat/completions", json={
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "temperature": 0,
                    # Reasoning + tool arguments must fit: 512 was observed
                    # truncating long code arguments before the call fired.
                    "max_tokens": 1024,
                })
                r.raise_for_status()
                message = r.json()["choices"][0]["message"]
                verdict = _validate_tool_call(message, expected, required)
                cats[verdict] = cats.get(verdict, 0) + 1
                rows.append({"prompt": prompt[:48], "expected": expected,
                             "verdict": verdict})
    total = sum(cats.values())
    result = {"bench": "tool_calls", "rows": rows, "categories": cats,
              "ok_rate": round(cats.get("ok", 0) / total, 3) if total else 0,
              "vram_mib": _vram_mib()}
    _save(result)
    return result


LOOP_SCENARIOS = [
    ("Quelle est la météo à Lyon ? Réponds ensuite en une phrase.",
     "get_weather", '{"city": "Lyon", "unit": "C"}',
     '{"temperature_c": 18, "condition": "nuageux"}'),
    ("Calcule 7*1234 avec Python puis donne le résultat.",
     "run_python", '{"code": "print(7*1234)"}',
     '{"stdout": "8638"}'),
]


def bench_loop(base: str, max_turns: int = 4) -> dict:
    """Minimal agent loop: call tool, feed result, expect a plain answer."""
    rows = []
    with httpx.Client(base_url=base, timeout=180) as client:
        for question, tool, args, tool_result in LOOP_SCENARIOS:
            messages = [{"role": "user", "content": question}]
            outcome, turns = "no_tool", 0
            for turn in range(1, max_turns + 1):
                r = client.post("/v1/chat/completions", json={
                    "messages": messages, "tools": TOOLS,
                    "tool_choice": "auto", "temperature": 0, "max_tokens": 400,
                })
                r.raise_for_status()
                message = r.json()["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                if not calls:
                    outcome = "answered" if turn > 1 else "no_tool"
                    turns = turn
                    break
                name = calls[0].get("name") or calls[0].get("function", {}).get("name")
                messages.append(message)
                messages.append({"role": "tool",
                                 "tool_call_id": calls[0].get("id", "call_1"),
                                 "name": name or tool,
                                 "content": tool_result if name == tool else "{}"})
            else:
                outcome, turns = "looped", max_turns
            rows.append({"question": question[:40], "outcome": outcome, "turns": turns})
    result = {"bench": "agent_loop", "rows": rows, "vram_mib": _vram_mib()}
    _save(result)
    return result


# ------------------------------------------------------------------ report

def _print(title: str, result: dict, columns: list[str]) -> None:
    print(f"\n== {title} ==")
    for row in result["rows"]:
        print(" | ".join(f"{c}={row.get(c)}" for c in columns))
    for key in ("best_tok_s", "ok_rate", "categories"):
        if key in result:
            print(f"{key}: {result[key]}")
    print(f"vram_mib: {result.get('vram_mib')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["gen", "ttft", "cache", "tools", "loop", "all"])
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=128)
    args = ap.parse_args()

    print(f"target: {args.base}  vram_now={_vram_mib()} MiB")
    if args.bench in ("gen", "all"):
        _print("generation", bench_generation(args.base, runs=args.runs),
               ["run", "predicted_n", "tok_s", "prompt_per_second"])
    if args.bench in ("ttft", "all"):
        _print("ttft", bench_ttft(args.base, max_tokens=args.max_tokens),
               ["prefix_target_tokens", "attempt", "prompt_tokens", "ttft_ms",
                "total_ms", "completion_tokens"])
    if args.bench in ("cache", "all"):
        _print("cache", bench_cache(args.base),
               ["call", "prompt_n", "prompt_ms", "prompt_per_second"])
    if args.bench in ("tools", "all"):
        _print("tool_calls", bench_tools(args.base), ["expected", "verdict"])
    if args.bench in ("loop", "all"):
        _print("agent_loop", bench_loop(args.base), ["outcome", "turns"])
    print(f"\nresults appended to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
