"""Validation locale complète — la CI du projet, en une commande.

Usage :
  python -m scripts.validate_all            # statique + tests (sans runtime)
  python -m scripts.validate_all --live     # + évals agent + budget perf
                                              (nécessite le router démarré)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(name: str, command: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n=== {name} ===")
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=str(cwd))
    ok = result.returncode == 0
    print(f"--- {name}: {'OK' if ok else 'ÉCHEC'} ---")
    return ok


def main() -> None:
    live = "--live" in sys.argv
    steps: list[tuple[str, list[str]]] = [
        ("compileall", [PYTHON, "-m", "compileall", "-q",
                        "chat", "core", "coding", "scripts", "tests"]),
        ("js agent", ["node", "--check", "chat/web/agent.js"]),
        ("js app", ["node", "--check", "chat/web/app.js"]),
        ("js workspace", ["node", "--check", "chat/web/workspace.js"]),
        ("js tests", ["node", "--test",
                      "tests/js/math-renderer.test.cjs",
                      "tests/js/progressive-renderer.test.cjs",
                      "tests/js/answer-stream.test.cjs",
                      "tests/js/api-client.test.cjs"]),
        ("imports", [PYTHON, "-m", "scripts.check_imports"]),
        ("pytest", [PYTHON, "-m", "pytest", "-p", "no:cacheprovider"]),
        ("pip check", [PYTHON, "-m", "pip", "check"]),
    ]
    if live:
        steps += [
            ("évals agent E4B", [PYTHON, "-m", "scripts.eval_agents",
                                 "--model", "gemma-4-e4b"]),
            ("budget perf 12B", [PYTHON, "-m", "scripts.check_perf",
                                 "--model", "gemma-4-12b"]),
            ("budget perf E4B", [PYTHON, "-m", "scripts.check_perf",
                                 "--model", "gemma-4-e4b"]),
        ]

    failures = [name for name, command in steps if not run(name, command)]
    print("\n" + "=" * 50)
    if failures:
        print(f"VALIDATION ÉCHOUÉE : {', '.join(failures)}")
        raise SystemExit(1)
    print(f"VALIDATION COMPLÈTE : {len(steps)} étapes OK"
          + (" (mode live)" if live else ""))


if __name__ == "__main__":
    main()
