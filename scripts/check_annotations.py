"""Recherche les annotations évaluées à l'exécution avec un nom non importé.

Pourquoi ce script existe : le poste de développement tourne en Python 3.14,
où les annotations ne sont plus évaluées au chargement du module (PEP 649).
Un fichier qui écrit `List[str]` sans importer `List` passe donc TOUS les tests
en local et échoue sur 3.11/3.12, à la collecte de pytest — la CI l'a montré
sur `tests/test_agent_core.py`, un bug présent dans `main` depuis des mois.

Le contrôle est statique (AST) : il ne dépend pas de la version de Python qui
l'exécute, donc il détecte le problème même sur 3.14.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Noms de `typing` les plus courants. La liste n'a pas besoin d'être complète :
# elle couvre ce qui est réellement écrit dans ce dépôt.
TYPING_NAMES = {
    "Any", "Callable", "Dict", "Iterable", "Iterator", "List", "Literal",
    "Mapping", "Match", "Optional", "Sequence", "Set", "Tuple", "Type",
    "Union",
}
SKIP_PARTS = {".venv", "__pycache__", "archive", "vendor", "node_modules"}


def imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def guarded_by_future_annotations(tree: ast.AST) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = imported_names(tree)
    # `from __future__ import annotations` rend TOUTES les annotations
    # paresseuses : plus rien n'est évalué au chargement. C'est la protection
    # la plus solide, et elle doit figurer en tête de chaque module.
    if guarded_by_future_annotations(tree):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in TYPING_NAMES and node.id not in imported:
                found.append(f"ligne {node.lineno} : {node.id}")
    return found


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    targets = [
        *root.joinpath("chat").rglob("*.py"),
        *root.joinpath("core").rglob("*.py"),
        *root.joinpath("coding").rglob("*.py"),
        *root.joinpath("scripts").rglob("*.py"),
        *root.joinpath("tests").rglob("*.py"),
    ]
    problems: list[tuple[Path, list[str]]] = []
    for path in sorted(targets):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            found = offenders(path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append((path, [f"illisible : {exc}"]))
            continue
        if found:
            problems.append((path, found))

    if not problems:
        print("annotations : aucun nom de typing utilisé sans import")
        return
    print("annotations évaluées à l'exécution avec un nom non importé :")
    for path, details in problems:
        print(f"  {path}")
        for detail in details:
            print(f"    {detail}")
    print(
        "\nCorrectif : soit importer le nom depuis typing, soit ajouter\n"
        "« from __future__ import annotations » en tête du module."
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
