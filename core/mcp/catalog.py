"""Catalogue des serveurs MCP stdio réellement lançables.

Les valeurs d'environnement ne sont jamais journalisées. ``env`` d'une spec
ne contient que les variables ajoutées au process enfant.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from core.mcp.types import (
    McpServerSpec,
    SERVER_ARXIV,
    SERVER_BRAVE,
    SERVER_CHART,
    SERVER_CONTEXT7,
    SERVER_EXA,
    SERVER_FETCH,
    SERVER_FRESHNESS,
    SERVER_FS,
    SERVER_GIT,
    SERVER_GITHUB,
    SERVER_SQLITE,
    SERVER_TAVILY,
    SERVER_TIME,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OFF = frozenset({"0", "false", "off", "no"})
# 0.2.23 est dans le dépôt amont mais absent du registre npm (dernier : 0.2.22).
_TAVILY_PACKAGE = "tavily-mcp@0.2.22"
_CATALOG_CACHE: tuple[tuple[str, ...], list[McpServerSpec]] | None = None


def build_catalog() -> list[McpServerSpec]:
    """Serveurs dont l'exécutable est résolu et les prérequis sont présents.

    Le résultat est mis en cache pour la vie du process : chaque message
    ne relance pas ``which`` ni la création des dossiers.
    """
    global _CATALOG_CACHE
    key = _catalog_key()
    if _CATALOG_CACHE is not None and _CATALOG_CACHE[0] == key:
        return _CATALOG_CACHE[1]
    specs = _build_catalog()
    _CATALOG_CACHE = (key, specs)
    return specs


def clear_catalog_cache() -> None:
    """Oublie le cache. Utile si l'environnement change dans un test."""
    global _CATALOG_CACHE
    _CATALOG_CACHE = None


def _catalog_key() -> tuple[str, ...]:
    """Empreinte des réglages, sans les valeurs secrètes."""
    flags = (
        "EXA_API_KEY",
        "BRAVE_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "TAVILY_API_KEY",
        "CONTEXT7_API_KEY",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GITHUB_TOKEN",
    )
    return (
        os.environ.get("LASME_MCP_ENABLED", ""),
        os.environ.get("LASME_MCP_DISABLED", ""),
        os.environ.get("LASME_MCP_FS_ROOT", ""),
        os.environ.get("LASME_MCP_SQLITE_PATH", ""),
        os.environ.get("LASME_MCP_GIT_REPO", ""),
        *(
            "1" if (os.environ.get(name) or "").strip() else ""
            for name in flags
        ),
    )


def _build_catalog() -> list[McpServerSpec]:
    if not _mcp_enabled():
        return []
    disabled = _disabled_ids()
    project = _PROJECT_ROOT
    npx = _which("npx")
    uvx = _which("uvx")
    specs: list[McpServerSpec] = []
    _collect(specs, disabled, SERVER_EXA, lambda: _exa(npx))
    _collect(specs, disabled, SERVER_BRAVE, lambda: _brave(npx))
    _collect(specs, disabled, SERVER_TAVILY, lambda: _tavily(npx))
    _collect(specs, disabled, SERVER_FETCH, lambda: _fetch(uvx))
    _collect(specs, disabled, SERVER_ARXIV, lambda: _arxiv(uvx, project))
    _collect(specs, disabled, SERVER_CONTEXT7, lambda: _context7(npx))
    _collect(specs, disabled, SERVER_GITHUB, lambda: _github(npx))
    _collect(specs, disabled, SERVER_GIT, lambda: _git(uvx, project))
    _collect(specs, disabled, SERVER_FS, lambda: _filesystem(npx, project))
    _collect(specs, disabled, SERVER_SQLITE, lambda: _sqlite(uvx, project))
    _collect(specs, disabled, SERVER_CHART, lambda: _chart(npx))
    _collect(specs, disabled, SERVER_TIME, lambda: _time(uvx))
    _collect(specs, disabled, SERVER_FRESHNESS, lambda: _freshness(project))
    return specs


def configured_server_ids() -> set[str]:
    """Identifiants retenus par :func:`build_catalog`."""
    return {spec.id for spec in build_catalog()}


def _collect(
    specs: list[McpServerSpec],
    disabled: set[str],
    server_id: str,
    build: Callable[[], McpServerSpec | None],
) -> None:
    if server_id.casefold() in disabled:
        return
    spec = build()
    if spec is not None:
        specs.append(spec)


def _mcp_enabled() -> bool:
    raw = os.environ.get("LASME_MCP_ENABLED")
    if raw is None or not raw.strip():
        return True
    return raw.strip().casefold() not in _OFF


def _disabled_ids() -> set[str]:
    raw = os.environ.get("LASME_MCP_DISABLED", "")
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}


def _which(executable: str) -> str | None:
    resolved = shutil.which(executable)
    return resolved or None


def _present(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value
    return None


def _freeze(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(values))


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return path.is_dir()


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))


def _exposes_repo(root: Path, project: Path) -> bool:
    """True si ``root`` est le dépôt ou un ancêtre (``.env`` y serait lisible)."""
    root_key = _norm(root)
    project_key = _norm(project)
    if project_key == root_key:
        return True
    prefix = root_key.rstrip("\\/") + os.sep
    return project_key.startswith(prefix)


def _exa(npx: str | None) -> McpServerSpec | None:
    key = _present("EXA_API_KEY")
    if npx is None or key is None:
        return None
    # Le README courant (stdio 3.x) n'accepte pas l'argument CLI ``tools=``.
    # Les outils par défaut sont web_search_exa et web_fetch_exa.
    return McpServerSpec(
        id=SERVER_EXA,
        title="Recherche Exa",
        command=npx,
        args=("-y", "exa-mcp-server"),
        env=_freeze({"EXA_API_KEY": key}),
    )


def _brave(npx: str | None) -> McpServerSpec | None:
    key = _present("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY")
    if npx is None or key is None:
        return None
    return McpServerSpec(
        id=SERVER_BRAVE,
        title="Recherche Brave",
        command=npx,
        args=("-y", "@brave/brave-search-mcp-server"),
        env=_freeze(
            {
                "BRAVE_API_KEY": key,
                "BRAVE_MCP_ENABLED_TOOLS": "brave_web_search brave_news_search",
            }
        ),
    )


def _tavily(npx: str | None) -> McpServerSpec | None:
    key = _present("TAVILY_API_KEY")
    if npx is None or key is None:
        return None
    return McpServerSpec(
        id=SERVER_TAVILY,
        title="Recherche Tavily",
        command=npx,
        args=("-y", _TAVILY_PACKAGE),
        env=_freeze({"TAVILY_API_KEY": key}),
    )


def _fetch(uvx: str | None) -> McpServerSpec | None:
    if uvx is None:
        return None
    return McpServerSpec(
        id=SERVER_FETCH,
        title="Récupération HTTP",
        command=uvx,
        args=("mcp-server-fetch",),
    )


def _arxiv(uvx: str | None, project: Path) -> McpServerSpec | None:
    if uvx is None:
        return None
    storage = (project / "data" / "mcp" / "arxiv").resolve()
    if not _ensure_dir(storage):
        return None
    return McpServerSpec(
        id=SERVER_ARXIV,
        title="Archive arXiv",
        command=uvx,
        args=("arxiv-mcp-server", "--storage-path", str(storage)),
    )


def _context7(npx: str | None) -> McpServerSpec | None:
    if npx is None:
        return None
    spec = McpServerSpec(
        id=SERVER_CONTEXT7,
        title="Docs Context7",
        command=npx,
        args=("-y", "@upstash/context7-mcp"),
    )
    key = _present("CONTEXT7_API_KEY")
    if key is None:
        return spec
    return McpServerSpec(
        id=spec.id,
        title=spec.title,
        command=spec.command,
        args=spec.args,
        env=_freeze({"CONTEXT7_API_KEY": key}),
    )


def _github(npx: str | None) -> McpServerSpec | None:
    token = _present("GITHUB_PERSONAL_ACCESS_TOKEN", "GITHUB_TOKEN")
    if npx is None or token is None:
        return None
    return McpServerSpec(
        id=SERVER_GITHUB,
        title="API GitHub",
        command=npx,
        args=("-y", "@modelcontextprotocol/server-github"),
        env=_freeze({"GITHUB_PERSONAL_ACCESS_TOKEN": token}),
    )


def _git(uvx: str | None, project: Path) -> McpServerSpec | None:
    if uvx is None:
        return None
    raw = os.environ.get("LASME_MCP_GIT_REPO", "").strip()
    repo = Path(raw) if raw else project
    if not repo.is_absolute():
        repo = project / repo
    repo = repo.resolve()
    if not repo.is_dir():
        return None
    return McpServerSpec(
        id=SERVER_GIT,
        title="Dépôt Git",
        command=uvx,
        args=("mcp-server-git", "--repository", str(repo)),
    )


def _filesystem(npx: str | None, project: Path) -> McpServerSpec | None:
    if npx is None:
        return None
    raw = os.environ.get("LASME_MCP_FS_ROOT", "").strip()
    if raw:
        root = Path(raw)
        if not root.is_absolute():
            root = project / root
    else:
        root = project / "data" / "mcp-workspace"
    root = root.resolve()
    if _exposes_repo(root, project.resolve()):
        return None
    if not _ensure_dir(root):
        return None
    return McpServerSpec(
        id=SERVER_FS,
        title="Fichiers sandbox",
        command=npx,
        args=("-y", "@modelcontextprotocol/server-filesystem", str(root)),
    )


def _sqlite(uvx: str | None, project: Path) -> McpServerSpec | None:
    if uvx is None:
        return None
    raw = os.environ.get("LASME_MCP_SQLITE_PATH", "").strip()
    if raw:
        database = Path(raw)
        if not database.is_absolute():
            database = project / database
    else:
        database = project / "data" / "mcp" / "analysis.sqlite"
    database = database.resolve()
    env_file = (project / ".env").resolve()
    if _norm(database) == _norm(env_file):
        return None
    if database.exists() and not database.is_file():
        return None
    if not _ensure_dir(database.parent):
        return None
    return McpServerSpec(
        id=SERVER_SQLITE,
        title="SQLite d'analyse",
        command=uvx,
        args=("mcp-server-sqlite", "--db-path", str(database)),
    )


def _chart(npx: str | None) -> McpServerSpec | None:
    if npx is None:
        return None
    return McpServerSpec(
        id=SERVER_CHART,
        title="Graphiques",
        command=npx,
        args=("-y", "@antv/mcp-server-chart"),
    )


def _time(uvx: str | None) -> McpServerSpec | None:
    if uvx is None:
        return None
    return McpServerSpec(
        id=SERVER_TIME,
        title="Heure",
        command=uvx,
        args=("mcp-server-time",),
    )


def _freshness(project: Path) -> McpServerSpec | None:
    executable = sys.executable
    if not executable or not Path(executable).is_file():
        return None
    return McpServerSpec(
        id=SERVER_FRESHNESS,
        title="Fraîcheur",
        command=executable,
        args=("-m", "core.mcp.servers.freshness"),
        cwd=str(project),
    )
