r"""Contrôle des dépendances entre couches (phase B3).

Règles imposées — un module n'importe que dans son périmètre :

- ``core/`` ne dépend JAMAIS de ``chat/`` ni ``coding/`` (socle indépendant) ;
- ``chat/contracts`` → ``core`` uniquement ;
- ``chat/server/services`` → ``chat.contracts``, ``core``, ``chat.server.deps`` ;
- ``chat/server/modules`` → contrats, services, deps, ``core``, ``coding``,
  et ``chat.server.modules.documents`` (façade d'indexation) ;
- ``chat/server/app`` → tout sauf ``chat.server.main`` ;
- interdiction absolue : un import de ``chat.server.main`` depuis les
  modules (la racine de composition ne peut être une dépendance).

Usage : ``python -m scripts.check_imports`` (exécuté par validate_all).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+((?:chat|core|coding)(?:\.[\w.]+)?)"
)

FORBIDDEN = [
    # (préfixe du fichier, import interdit, raison)
    ("core/", "chat.", "core/ ne doit jamais dépendre de chat/"),
    ("core/", "coding.", "core/ ne doit jamais dépendre de coding/"),
    ("chat/contracts", "chat.server", "les contrats ne dépendent pas du serveur"),
    ("chat/server/services", "chat.server.modules", "les services ignorent les routes"),
    ("chat/server/modules", "chat.server.main", "les modules ignorent la racine main"),
    ("chat/server/deps", "chat.server.modules", "deps ne dépend pas des modules"),
    ("chat/server/deps", "chat.server.app", "deps ne dépend pas de la factory"),
]


def module_files():
    for base in ("core", "chat", "coding"):
        for path in (ROOT / base).rglob("*.py"):
            yield path


def check() -> list[str]:
    problems: list[str] = []
    for path in module_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(text):
            target = match.group(1)
            for prefix, forbidden, reason in FORBIDDEN:
                if rel.startswith(prefix) and target.startswith(forbidden):
                    problems.append(f"{rel} → {target} : {reason}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Dépendances interdites :")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK - matrice de dépendances respectée")
    return 0


if __name__ == "__main__":
    sys.exit(main())
