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


# Courtes réserves employées en remplacement d'une phrase inventée.
# Un ton de conversation — jamais une formule de refus administratif.
# Écrite SANS point final : la ponctuation de la phrase d'origine est
# conservée par le découpage, sinon on obtenait « …affirmer.. ».
_NUMBER_RESERVE = (
    "je n'ai pas de chiffre fiable là-dessus dans mes sources, "
    "je préfère ne rien affirmer"
)
# Variante employée quand la phrase portait un intitulé (« **Sécurité** : … »).
# Jeter l'intitulé avec le chiffre donnait une puce muette, réduite à la
# réserve : le lecteur perdait le SUJET dont on ne savait rien.
_LABEL_RE = re.compile(
    r"^(?:\*\*[^*]{2,80}\*\*|\*\*[^*]{2,80}\*\*[^:\n]{0,40}|"
    r"[A-Za-zÀ-ÿ0-9][^:\n]{1,80})\s*:\s*"
)
_LABEL_UNVERIFIED = "je n'ai pas de chiffre fiable dans mes sources"

# Découpage par PHRASE à l'intérieur d'une ligne, séparateurs CONSERVÉS
# (re.split avec un groupe capturant : la concaténation redonne la ligne
# exacte). Deux garde-fous appris en réel :
#   - les sauts de ligne ne sont jamais franchis : une liste markdown doit
#     rester une liste (l'ancien découpage sur tout blanc réunissait les
#     puces en un seul paragraphe) ;
#   - un point ne termine une phrase que s'il est suivi d'un blanc ou de la
#     fin de ligne, sinon « Terminal-Bench 4.0 » était coupé en deux et la
#     réserve s'insérait AU MILIEU du nombre.
_SENTENCE_SPLIT_RE = re.compile(r"([.!?…]+(?:\s+|$))")
# Préfixe markdown conservé lorsqu'une phrase doit être remplacée.
_LINE_PREFIX_RE = re.compile(r"^\s*(?:(?:[-*+•]|\d+[.)]|>)\s+)*")
# Ligne de tableau markdown : la réserve longue y casserait la grille, on
# remplace la valeur fautive par la mention prévue par le prompt strict.
_TABLE_ROW_RE = re.compile(r"\|")
_TABLE_RESERVE = "non vérifié"


def _evidence_numbers(evidence: str) -> set:
    return {
        match.replace(",", ".")
        for match in re.findall(r"\d+(?:[.,]\d+)?", evidence or "")
    }


def _soften_table_row(line: str, evidence: str) -> str:
    evidence_numbers = _evidence_numbers(evidence)

    def _replace(match: Match[str]) -> str:
        claim = match.group(0)
        claim_numbers = {
            value.replace(",", ".")
            for value in re.findall(r"\d+(?:[.,]\d+)?", claim)
        }
        if claim_numbers and not claim_numbers.issubset(evidence_numbers):
            return _TABLE_RESERVE
        return claim

    return _SENSITIVE_NUMBER_PATTERN.sub(_replace, line)


def _soften_line(line: str, evidence: str) -> str:
    if _TABLE_ROW_RE.search(line):
        return _soften_table_row(line, evidence)
    pieces = _SENTENCE_SPLIT_RE.split(line)
    for index in range(0, len(pieces), 2):
        sentence = pieces[index]
        if not sentence.strip():
            continue
        if not unsupported_grounded_numbers(sentence, evidence):
            continue
        bullet = _LINE_PREFIX_RE.match(sentence).group(0)
        body = sentence[len(bullet):]
        # Un intitulé (« **Sécurité** : … ») est conservé : c'est lui qui dit
        # DE QUOI on ne sait rien. Seul le contenu chiffré disparaît.
        label = _LABEL_RE.match(body)
        if label:
            # Après un intitulé, la minuscule est correcte en français et se
            # lit mieux : « **Sécurité** : je n'ai pas de chiffre fiable… ».
            pieces[index] = f"{bullet}{label.group(0)}{_LABEL_UNVERIFIED}"
        else:
            reserve = _NUMBER_RESERVE[0].upper() + _NUMBER_RESERVE[1:]
            pieces[index] = f"{bullet}{reserve}"
    softened = "".join(pieces)
    # Le découpage conserve la ponctuation de l'original : quand la phrase
    # remplacée était la dernière et n'en portait aucune, on en ajoute une.
    if softened.rstrip() and not softened.rstrip().endswith(
        (".", "!", "?", "…", ":", ";", ",")
    ):
        softened = f"{softened.rstrip()}."
    return softened


def soften_unsupported_numbers(answer: str, evidence: str) -> str:
    """Assagit les chiffres non étayés, phrase par phrase, sans rien jeter.

    Cas réel qui a motivé cette fonction : face aux « scores d'Opus 5.5 »,
    une seule phrase bâtie sur un chiffre non étayé faisait remplacer
    L'INTÉGRALITÉ de la réponse par un refus administratif — y compris la
    question de clarification qui la suivait et qui était pourtant la bonne
    chose à dire. Ici, seules les phrases incriminées sont assagies.

    La mise en page est conservée OCTET POUR OCTET (sauts de ligne, puces,
    numérotation) : le texte n'est jamais réassemblé différemment.
    """
    text = str(answer or "")
    if not text:
        return text
    return "\n".join(_soften_line(line, evidence) for line in text.split("\n"))


def ground_strict_answer(answer: str, evidence: str) -> str:
    """Politique stricte : assagir la réponse, jamais l'effacer.

    Une réponse n'est JAMAIS remplacée en bloc. L'ancienne politique, sans
    page lue, jetait tout et ne laissait qu'un refus administratif — y
    compris sur une RELANCE portant sur des faits déjà sourcés dans le fil
    (« et par rapport à Fable 5.1 ? ») et alors que l'agent venait de bien
    répondre. Le lecteur voyait sa réponse s'écrire puis disparaître.

    On ne retire ici que les valeurs numériques (prix, pourcentages)
    absentes des preuves : le raisonnement, les comparaisons qualitatives,
    les listes et les questions de clarification restent intacts.
    """
    text = str(answer or "")
    if not text:
        return text
    return soften_unsupported_numbers(text, evidence)


def grounding_evidence_text(*blocks: Any, max_chars: int = 24_000) -> str:
    """Réunit des blocs de preuve hétérogènes en un seul texte borné.

    Accepte des chaînes (pages réellement lues par l'agent) et des listes de
    sources (``{"title", "snippet", "url"}``) : résultats de recherche du
    tour courant et sources déjà citées plus tôt dans la conversation.

    Une relance s'appuie sur ce qui a été vérifié avant : sans les sources du
    fil, les chiffres déjà sourcés passaient pour des inventions et la
    réponse était dégradée.
    """
    parts: List[str] = []
    remaining = max(0, int(max_chars))
    for block in blocks:
        if remaining <= 0:
            break
        if isinstance(block, str):
            text = block.strip()
        else:
            entries = []
            for item in block or []:
                if not isinstance(item, dict):
                    continue
                entries.append(
                    " ".join(
                        str(item.get(field) or "")
                        for field in ("title", "snippet", "url")
                    ).strip()
                )
            text = "\n".join(entry for entry in entries if entry)
        if not text:
            continue
        parts.append(text[:remaining])
        remaining -= len(parts[-1])
    return "\n".join(parts)


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
