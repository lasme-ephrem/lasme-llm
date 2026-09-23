"""Grounding gates used by the chat, independent of any search engine.

Prices, versions, benchmarks and current facts must not fall back to the
model's training memory. Classification is accent-insensitive so French
variants such as ``coût`` and ``coûts`` stay consistent.
"""

from __future__ import annotations

import re
import unicodedata

COMPLEX_MARKERS = {
    "analyse", "compare", "comparaison", "comparatif", "comparatifs",
    "controverse", "difference",
    "differents", "enjeux", "evalue", "evolution", "impact", "impacts",
    "limites", "perspectives", "pourquoi", "rapport", "synthese",
}
TEMPORAL_MARKERS = {
    "actuel", "actuelle", "actualite", "actualites", "aujourd", "dernier",
    "derniers", "derniere", "dernieres", "maintenant", "nouveau", "nouveaux",
    "nouvelle", "nouvelles", "recent", "recents", "recente", "recentes",
    "score", "version", "versions",
}
COMMERCIAL_MARKERS = {
    "abonnement", "abonnements", "cout", "couts", "price", "prices", "prix",
    "pricing", "tarif", "tarifs",
}
VOLATILE_PRODUCT_MARKERS = {
    "api", "benchmark", "benchmarks", "classement", "disponibilite",
    "disponible", "llm", "modele", "modeles", "offre", "offres", "performance",
    "performances", "produit", "produits", "service", "services", "specification",
    "specifications",
}


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def requires_strict_grounding(query: str) -> bool:
    """Identify factual requests that must not fall back to model memory.

    Prices, product availability, model specifications, benchmarks and current
    facts change too often to be answered safely from a local model's training
    data.  The helper intentionally works on accent-normalized text so French
    variants such as ``coût`` and ``coûts`` are classified consistently.
    """
    terms = set(normalize_search_text(query).split())
    if not terms:
        return False
    if terms.intersection(COMMERCIAL_MARKERS | TEMPORAL_MARKERS):
        return True
    if terms.intersection({"benchmark", "benchmarks", "classement"}):
        return True
    comparison = bool(terms.intersection(COMPLEX_MARKERS))
    return comparison and bool(terms.intersection(VOLATILE_PRODUCT_MARKERS))


def is_commercial_comparison(query: str) -> bool:
    terms = set(normalize_search_text(query).split())
    return bool(
        terms.intersection(COMMERCIAL_MARKERS)
        and (
            terms.intersection(COMPLEX_MARKERS)
            or terms.intersection(VOLATILE_PRODUCT_MARKERS)
        )
    )
