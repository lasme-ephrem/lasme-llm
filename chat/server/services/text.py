"""Nettoyage et sanitisation du texte généré (citations inclus).

Extraits de ``chat/server/main.py`` (refonte modulaire) : comportement
identique — conservés tels quels car les tests de citations en dépendent.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterator, List, Match

_MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "ðŸ")
_MOJIBAKE_REPLACEMENTS = {
    "â€™": "’",
    "â€˜": "‘",
    "â€œ": "“",
    "â€": "”",
    "â€“": "–",
    "â€”": "—",
    "Â·": "·",
}


def clean_model_text(value: str) -> str:
    """Normalize generated text and remove stray non-Latin script letters."""
    text = unicodedata.normalize("NFC", value or "").replace("\ufffd", "")
    if any(marker in text for marker in _MOJIBAKE_MARKERS):
        try:
            repaired = text.encode("cp1252").decode("utf-8")
            if sum(repaired.count(marker) for marker in _MOJIBAKE_MARKERS) < sum(
                text.count(marker) for marker in _MOJIBAKE_MARKERS
            ):
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    for broken, replacement in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken, replacement)
    text = text.replace("Â", "")

    cleaned = []
    for character in text:
        if character in {"\n", "\r", "\t"}:
            cleaned.append(character)
            continue
        category = unicodedata.category(character)
        if category.startswith("C"):
            continue
        if category.startswith("L") and ord(character) > 127:
            character_name = unicodedata.name(character, "")
            if not any(
                allowed_script in character_name
                for allowed_script in {"LATIN", "GREEK"}
            ):
                continue
        cleaned.append(character)
    return "".join(cleaned)


def iter_stream_text_chunks(
    value: str,
    target_chars: int = 64,
) -> Iterator[str]:
    """Split completed provider answers into natural SSE-sized deltas."""
    text = str(value or "")
    if not text:
        return
    target = max(16, int(target_chars))
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            space_break = text.rfind(" ", start + target // 2, end + 1)
            newline_break = text.rfind("\n", start + target // 2, end + 1)
            natural_break = max(space_break, newline_break)
            if natural_break >= 0:
                end = natural_break + 1
        yield text[start:end]
        start = end


_WEB_CODE_BLOCK_RE = re.compile(
    r"(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\r\n]*`)"
)


def strip_web_citation_markers(value: str) -> str:
    """Remove numeric Web citations from prose while preserving code."""
    text = str(value or "")
    if not text:
        return ""
    parts = _WEB_CODE_BLOCK_RE.split(text)
    citation_pattern = re.compile(
        r"[ \t]*(?:"
        r"\[(?:source\s*:?\s*)?\d+(?:\s*[,–-]\s*\d+)*\]"
        r"|\((?:source\s*:?\s*)?\d+\)"
        r")",
        flags=re.IGNORECASE,
    )
    dangling_pattern = re.compile(
        r"[ \t]*\[(?:source\s*:?\s*)?\d+"
        r"(?:\s*[,–-]\s*\d+)*\s*$",
        flags=re.IGNORECASE,
    )
    for index in range(0, len(parts), 2):
        parts[index] = citation_pattern.sub("", parts[index])
        parts[index] = dangling_pattern.sub("", parts[index])
        parts[index] = re.sub(
            r"[ \t]+([,.;:!?])",
            r"\1",
            parts[index],
        )
    return "".join(parts)



_SENSITIVE_NUMBER_PATTERN = re.compile(
    r"(?:[$€£¥]\s*\d+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?\s*(?:[$€£¥]|USD|EUR|CNY|RMB|%|pour\s+cent))",
    flags=re.IGNORECASE,
)


def unsupported_grounded_numbers(
    answer: str,
    evidence: str,
) -> List[str]:
    """Return price/percentage claims absent from the supplied evidence.

    This is deliberately narrower than generic number matching: list numbers,
    years and model names should not be rejected, while invented prices and
    benchmark percentages must never escape a strict grounded response.
    """
    evidence_numbers = {
        match.replace(",", ".")
        for match in re.findall(r"\d+(?:[.,]\d+)?", evidence or "")
    }
    unsupported: List[str] = []
    for claim in _SENSITIVE_NUMBER_PATTERN.findall(answer or ""):
        claim_numbers = {
            match.replace(",", ".")
            for match in re.findall(r"\d+(?:[.,]\d+)?", claim)
        }
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            unsupported.append(claim)
    return list(dict.fromkeys(unsupported))


def compact_web_source_metadata(
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist only the fields needed to restore the compact source drawer."""
    sources = []
    for index, item in enumerate((results or [])[:20]):
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        try:
            number = int(item.get("number") or index + 1)
        except (TypeError, ValueError):
            number = index + 1
        sources.append(
            {
                "title": title[:300],
                "url": url[:2_000],
                "engine": str(item.get("engine") or "")[:80],
                "snippet": str(item.get("snippet") or "")[:1_200],
                # Contrat citation : la puce [n] du frontend pointe sur
                # web_results[n-1] ; le numéro explicite suit la source
                # (défaut : sa position, alignée sur format_search_results).
                "number": max(1, number),
            }
        )
    return {"web_results": sources} if sources else {}


_SANITIZE_MARKER_RE = re.compile(
    r"\[(?:source\s*:?\s*)?(\d+(?:\s*[,–-]\s*\d+)*)\]"
    r"|\((?:source\s*:?\s*)?(\d+(?:\s*[,–-]\s*\d+)*)\)",
    flags=re.IGNORECASE,
)
_SOURCES_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,3}\s*)?(?:\*\*)?\s*(?:sources?|références?)"
    r"\s*(?::\s*(?:\*\*)?|\*\*)?\s*[:.]?\s*$",
    flags=re.IGNORECASE,
)
_SOURCES_LIST_LINE_RE = re.compile(
    r"^(?:[-*•>]\s+|\d+[.)]\s+|(?:https?://|www\.)\S+)"
)


def _strip_final_sources_section(text: str) -> str:
    """Retire une section « Sources »/« Références » TERMINALE.

    Prudent : la section n'est supprimée que si elle est en fin de texte
    (titre + lignes de liste / URLs brutes / lignes vides jusqu'au bout).
    Une section suivie d'autre prose est conservée telle quelle.
    """
    lines = text.splitlines()
    boundary = len(lines)
    while boundary > 0:
        line = lines[boundary - 1].strip()
        if not line or _SOURCES_LIST_LINE_RE.match(line):
            boundary -= 1
            continue
        break
    if boundary > 0 and _SOURCES_HEADING_RE.match(lines[boundary - 1]):
        start = boundary - 1
        while start > 0 and not lines[start - 1].strip():
            start -= 1
        return "\n".join(lines[:start]).rstrip()
    return text


def sanitize_citation_markers(text: str, source_count: int) -> str:
    """Contrat de citation côté serveur : garder les [n] valides.

    Le frontend remplace chaque marqueur [n] du texte final par la puce
    de ``web_results[n-1]``. Donc : (a) tout marqueur hors plage
    (n < 1 ou n > source_count) est retiré — et si source_count vaut 0,
    TOUS les marqueurs partent, aucun numéro ne pouvant pointer sur une
    source ; (b) une éventuelle section « Sources » finale que le modèle
    écrirait malgré la directive est supprimée ; (c) le contenu des blocs
    de code (fenced/inline) n'est jamais touché. Contrairement à
    ``strip_web_citation_markers`` (réservé aux réponses de fournisseurs
    et aux messages historiques), les marqueurs valides SURVICVENT : ils
    sont le mécanisme de citation, pas un résidu.
    """
    text = str(text or "")
    if not text:
        return ""
    try:
        count = max(0, int(source_count))
    except (TypeError, ValueError):
        count = 0
    parts = _WEB_CODE_BLOCK_RE.split(text)

    def _filter(match: Match[str]) -> str:
        raw = match.group(1) or match.group(2) or ""
        numbers = [int(value) for value in re.findall(r"\d+", raw)]
        if count > 0 and numbers and all(
            1 <= value <= count for value in numbers
        ):
            return match.group(0)
        return ""

    for index in range(0, len(parts), 2):
        cleaned = _SANITIZE_MARKER_RE.sub(_filter, parts[index])
        if cleaned != parts[index]:
            cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
            cleaned = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", cleaned)
        parts[index] = cleaned
    if parts:
        parts[-1] = _strip_final_sources_section(parts[-1])
    return "".join(parts)
