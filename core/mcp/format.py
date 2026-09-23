"""Mise en forme des résultats pour la recherche approfondie."""

from __future__ import annotations

import re
from typing import Any


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def format_search_results(results: list[dict[str, Any]]) -> str:
    """Balises ``source`` historiques. Vide → message fixe."""
    rows = [item for item in results or [] if isinstance(item, dict)]
    if not rows:
        return "Aucun résultat trouvé sur le Web."
    engine = str(rows[0].get("engine") or "").strip() or "Web Search"
    blocks = [f"### 🌐 DONNÉES WEB NON FIABLES (Moteur : {engine})"]
    for index, item in enumerate(rows, start=1):
        url = str(item.get("url") or "")
        title = _one_line(str(item.get("title") or ""))
        snippet = _one_line(str(item.get("snippet") or ""))
        blocks.append(
            f'<source id="{index}" url="{url}">\n'
            f"Titre: {title}\n"
            f"Type: Source pertinente, classée au rang {index}\n"
            "Preuve: extrait du moteur de recherche uniquement "
            "(non vérifiée par extraction)\n"
            f"Extrait: {snippet}\n"
            "</source>"
        )
    return "\n".join(blocks)
