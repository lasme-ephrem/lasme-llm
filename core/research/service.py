from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


def build_research_plan(question: str) -> List[Dict[str, str]]:
    """Build a transparent, bounded plan before any provider is called."""
    clean = " ".join((question or "").split()).strip()
    today = datetime.date.today().isoformat()
    historical = bool(
        re.search(
            r"\b(histoire|historique|origine|évolution|chronologie|depuis)\b",
            clean,
            flags=re.IGNORECASE,
        )
    )
    comparison = bool(
        re.search(
            r"\b(compare|comparatif|versus|différence|meilleur|avantage)\b",
            clean,
            flags=re.IGNORECASE,
        )
    )
    steps = [
        {
            "id": "primary",
            "label": "Sources primaires",
            "query": f"{clean} sources officielles données primaires au {today}",
        },
        {
            "id": "corroboration",
            "label": "Recoupement indépendant",
            "query": f"{clean} analyse indépendante faits vérifiés au {today}",
        },
    ]
    if historical:
        steps.append(
            {
                "id": "history",
                "label": "Contexte historique",
                "query": f"{clean} chronologie contexte historique",
            }
        )
    elif comparison:
        steps.append(
            {
                "id": "comparison",
                "label": "Comparaison des positions",
                "query": f"{clean} comparaison limites désaccords",
            }
        )
    else:
        steps.append(
            {
                "id": "verification",
                "label": "Contre-vérification",
                "query": f"{clean} vérification contradictions informations récentes",
            }
        )
    return steps


def merge_research_results(
    reports: Iterable[Dict[str, Any]],
    *,
    limit: int = 14,
) -> List[Dict[str, Any]]:
    """Deduplicate evidence while preserving the best-ranked occurrence."""
    merged: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        for item in report.get("results", []):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            parsed = urlparse(url)
            key = (
                f"{parsed.netloc.casefold()}"
                f"{parsed.path.rstrip('/').casefold()}"
            )
            candidate = dict(item)
            candidate["url"] = url
            candidate["domain"] = parsed.netloc.casefold()
            candidate["research_score"] = float(
                item.get("_score")
                or item.get("score")
                or item.get("relevance_score")
                or 0
            )
            previous = merged.get(key)
            if previous is None or candidate["research_score"] > previous[
                "research_score"
            ]:
                merged[key] = candidate
    ranked = sorted(
        merged.values(),
        key=lambda item: (
            bool(item.get("verified")),
            item.get("research_score", 0),
        ),
        reverse=True,
    )
    return ranked[: max(1, min(limit, 20))]
