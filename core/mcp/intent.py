"""Classification déterministe d'une requête de recherche (FR et EN)."""

from __future__ import annotations

import re
import unicodedata

INTENT_LABELS: dict[str, str] = {
    "news": "actualité",
    "sports": "sport",
    "weather": "météo",
    "academic": "recherche",
    "knowledge": "connaissance",
    "code": "code",
    "finance": "finance",
    "general": "général",
}

_WEATHER = (
    "meteo",
    "temps qu'il fait",
    "weather",
    "pluie",
    "temperature",
    "previsions",
)
_SPORTS = (
    "foot",
    "football",
    "soccer",
    "nba",
    "basket",
    "tennis",
    "rugby",
    "f1",
    "formule 1",
    "ligue 1",
    "ballon d'or",
    "coupe du monde",
    "match",
    "score",
    "classement",
    "vainqueur",
    "olympique",
    "buteur",
    "champions league",
)
_FINANCE = (
    "bitcoin",
    "btc",
    "ethereum",
    "bourse",
    "action",
    "cours de",
    "nasdaq",
    "cac 40",
    "prix du",
)
_ACADEMIC = (
    "arxiv",
    "doi",
    "paper",
    "publication scientifique",
    "etude scientifique",
    "nature.com",
)
_CODE = (
    "traceback",
    "stack trace",
    "npm",
    "pip install",
    "documentation de",
    "api reference",
    "github.com",
    "erreur python",
    "stackoverflow",
)
_KNOWLEDGE = (
    "qui est",
    "qu'est-ce",
    "definition",
    "wikipedia",
    "capitale de",
    "biographie",
)
_NEWS = (
    "actualite",
    "news",
    "aujourd'hui",
    "breaking",
    "election",
    "annonce",
    "guerre",
    "gouvernement",
    "president",
)
_TECH = (
    "ia",
    "llm",
    "nvidia",
    "puce",
    "logiciel",
    "apple",
    "google",
    "microsoft",
    "openai",
    "anthropic",
    "gpu",
)


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(
        char for char in folded if not unicodedata.combining(char)
    )
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _compile(phrase: str) -> re.Pattern[str]:
    tokens: list[str] = []
    for part in _normalize(phrase).split():
        piece = re.escape(part)
        if len(part) >= 4 and not part.endswith("s"):
            piece += "s?"
        tokens.append(piece)
    return re.compile(r" " + r" ".join(tokens) + r" ")


def _patterns(phrases: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(_compile(phrase) for phrase in phrases)


_WEATHER_RE = _patterns(_WEATHER)
_SPORTS_RE = _patterns(_SPORTS)
_FINANCE_RE = _patterns(_FINANCE)
_ACADEMIC_RE = _patterns(_ACADEMIC)
_CODE_RE = _patterns(_CODE)
_KNOWLEDGE_RE = _patterns(_KNOWLEDGE)
_NEWS_RE = _patterns(_NEWS)
_TECH_RE = _patterns(_TECH)


def _hit(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    padded = f" {text} "
    return any(pattern.search(padded) is not None for pattern in patterns)


def classify_intent(query: str) -> str:
    """Première catégorie spécifique ; sinon ``general``."""
    text = _normalize(query)
    if not text:
        return "general"
    if _hit(text, _WEATHER_RE):
        return "weather"
    if _hit(text, _SPORTS_RE):
        return "sports"
    if _hit(text, _FINANCE_RE):
        return "finance"
    if _hit(text, _ACADEMIC_RE):
        return "academic"
    if _hit(text, _CODE_RE):
        return "code"
    # knowledge cède si un mot sport, actu ou finance est déjà dans la requête
    if _hit(text, _KNOWLEDGE_RE) and not (
        _hit(text, _SPORTS_RE) or _hit(text, _NEWS_RE) or _hit(text, _FINANCE_RE)
    ):
        return "knowledge"
    if _hit(text, _NEWS_RE):
        return "news"
    return "general"


def is_tech_news(query: str) -> bool:
    """Vrai si la requête parle de tech (utile au routage actu)."""
    text = _normalize(query)
    if not text:
        return False
    return _hit(text, _TECH_RE)
