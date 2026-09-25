"""Sources Web découvertes par l'agent (web_research / web_read).

Extraits de ``chat/server/main.py`` (refonte modulaire) : re-parse des
journaux de run pour alimenter le drawer et la persistance au format des
résultats de recherche. Comportement identique.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

_AGENT_SEARCH_TITLE_RE = re.compile(r"^\[(\d+)\]\s+(.+?)\s*$")
_AGENT_SEARCH_URL_RE = re.compile(r"^\s+(https?://\S+)\s*$")
_AGENT_FETCH_URL_RE = re.compile(r"^##\s+(https?://\S+)")


def normalize_source_url(url: str) -> str:
    """Clé de déduplication d'une source : host sans www., sans schéma,
    sans slash final (chemin et query conservés tels quels)."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parts = urlparse(raw)
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{path}{query}"


def _title_from_url(url: str) -> str:
    """Titre lisible déduit d'une URL fetchée dont le titre est inconnu."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parts = urlparse(raw)
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    segments = [segment for segment in parts.path.split("/") if segment]
    label = unquote(segments[-1]) if segments else ""
    label = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", label)
    label = re.sub(r"[-_+]+", " ", label).strip()
    if not label:
        return host or raw
    return f"{label[:1].upper()}{label[1:]}"


def _iter_search_output_entries(output: str):
    """Triplets (numéro, titre, url) d'un output web_research : ligne
    « [n] titre » suivie de la ligne indentée « url » (format
    _format_search_results). Le numéro [n] est la position citable de la
    source dans la réponse du modèle (marqueur [n] ⇒ web_results[n-1])."""
    lines = str(output or "").splitlines()
    for index, line in enumerate(lines):
        header = _AGENT_SEARCH_TITLE_RE.match(line)
        if not header:
            continue
        if index + 1 < len(lines):
            url_match = _AGENT_SEARCH_URL_RE.match(lines[index + 1])
            if url_match:
                try:
                    number = int(header.group(1))
                except ValueError:
                    number = 0
                yield number, header.group(2).strip(), url_match.group(1)


def _iter_fetch_output_urls(output: str):
    """URLs réellement lues par web_read (« ## url (n caractères) »).
    Les sections en ERREUR (page non lue) ne sont pas des sources."""
    lines = str(output or "").splitlines()
    urls: List[str] = []
    for index, line in enumerate(lines):
        match = _AGENT_FETCH_URL_RE.match(line)
        if not match:
            continue
        body = lines[index + 1] if index + 1 < len(lines) else ""
        if body.lstrip().startswith("ERREUR"):
            continue
        urls.append(match.group(1))
    return urls


def extract_agent_sources(
    events: List[Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    """Sources Web que l'agent a trouvées via ses propres outils.

    Parcourt les tool_result du journal de run et parse les outputs de
    web_research (liens numérotés ; l'ancien nom web_search est encore
    accepté) et web_read (« ## url (n caractères) » ; l'ancien nom
    fetch_pages est encore accepté).

    Contrat interface : le modèle cite par marqueur [n] et le frontend
    affiche web_results[n-1]. Chaque résultat de web_research est donc
    placé à l'INDEX n-1 du numéro [n] affiché dans la sortie d'outil ;
    les positions non attribuées (trou de numérotation) sont rendues
    comme None — merge_dedup_sources les ignore. Une URL déjà vue ne
    duplique pas d'entrée : la première occurrence, à la plus petite
    position, gagne. Un titre réel de web_research prime sur un titre
    déduit de l'URL par web_read — et fait alors passer la source
    sans numéro (non citable) à sa position citable [n]. Les pages
    fetchées restées sans numéro sont ajoutées en fin de liste : elles
    n'ont jamais de marqueur, leur décalage n'affecte aucun [n].
    """
    numbered: Dict[int, Dict[str, Any]] = {}
    by_key: Dict[str, Dict[str, Any]] = {}
    unnumbered: List[Dict[str, Any]] = []

    def _register_search(number: int, title: str, url: str) -> None:
        key = normalize_source_url(url)
        if not key:
            return
        entry = by_key.get(key)
        if entry is None:
            entry = {
                "title": title[:300],
                "url": url[:2_000],
                "engine": "agent",
                "snippet": "",
            }
            by_key[key] = entry
            if number > 0:
                entry["number"] = number
                numbered[number] = entry
            else:
                unnumbered.append(entry)
        elif number > 0 and "number" not in entry:
            # URL d'abord vue via web_read (sans numéro) : le vrai
            # titre de la recherche et sa position citable sont adoptés.
            entry["title"] = title[:300]
            entry["number"] = number
            numbered[number] = entry
            unnumbered.remove(entry)
        # Sinon : premier numéro (plus petite position) conservé.

    def _register_fetch(url: str) -> None:
        key = normalize_source_url(url)
        if not key or key in by_key:
            return
        entry = {
            "title": _title_from_url(url)[:300],
            "url": url[:2_000],
            "engine": "agent",
            "snippet": "",
        }
        by_key[key] = entry
        unnumbered.append(entry)

    for event in events or []:
        if not isinstance(event, dict) or event.get("type") != "tool_result":
            continue
        name = str(event.get("name") or "")
        output = str(event.get("output") or "")
        if name in {"web_research", "web_search"}:
            for number, title, url in _iter_search_output_entries(output):
                _register_search(number, title, url)
        elif name in {"web_read", "fetch_pages"}:
            for url in _iter_fetch_output_urls(output):
                _register_fetch(url)

    if not numbered and not unnumbered:
        return []
    ordered: List[Optional[Dict[str, Any]]] = [None] * max(numbered, default=0)
    for number, entry in numbered.items():
        ordered[number - 1] = entry
    return ordered + unnumbered


def merge_dedup_sources(
    existing: List[Dict[str, Any]],
    extra: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fusionne deux listes de sources : l'existant d'abord (priorité
    pré-recherche, ordre conservé), les ajoutes en fin, sans doublon
    d'URL normalisée."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in list(existing or []) + list(extra or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        key = normalize_source_url(url)
        if not url or not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
