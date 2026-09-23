"""MCP façades for the agent, gated by model tier and server availability.

Registration never starts a stdio process. Availability is the injected
client, or ``configured_server_ids`` from ``core.mcp.catalog`` when no
client is injected. ``get_mcp_client`` is imported only when a handler
runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from core.agent.tools import (
    CATEGORY_EXEC,
    CATEGORY_NETWORK,
    CATEGORY_READ,
    ToolDefinition,
    ToolRegistry,
)
from core.mcp.tiers import model_tier, tools_for_tier
from core.mcp.types import (
    McpCallResult,
    SERVER_CHART,
    SERVER_CONTEXT7,
    SERVER_FS,
    SERVER_GIT,
    SERVER_GITHUB,
    SERVER_SQLITE,
    SERVER_TIME,
    TOOL_C7_DOCS,
    TOOL_C7_RESOLVE,
    TOOL_CHART_AREA,
    TOOL_CHART_BAR,
    TOOL_CHART_COLUMN,
    TOOL_CHART_LINE,
    TOOL_CHART_PIE,
    TOOL_CHART_SCATTER,
    TOOL_FS_LIST,
    TOOL_FS_READ,
    TOOL_FS_SEARCH,
    TOOL_GH_CODE,
    TOOL_GH_FILE,
    TOOL_GH_ISSUES,
    TOOL_GH_REPOS,
    TOOL_GIT_DIFF,
    TOOL_GIT_LOG,
    TOOL_GIT_STATUS,
    TOOL_SQL_READ,
    TOOL_TIME_CONVERT,
)

_MAX_CHARS = 8_000
_TRUNC_MARK = "\n…[sortie tronquée]"

_TIMEOUT_LIBRARY = 40.0
_TIMEOUT_GITHUB = 40.0
_TIMEOUT_GIT = 20.0
_TIMEOUT_FS = 20.0
_TIMEOUT_SQL = 20.0
_TIMEOUT_CHART = 60.0
_TIMEOUT_TIME = 15.0

# Lecture seule. git_commit et les autres outils d'écriture ne sont jamais appelés.
_GIT_ACTIONS = {
    "status": TOOL_GIT_STATUS,
    "log": TOOL_GIT_LOG,
    "diff": TOOL_GIT_DIFF,
}

_GH_KIND = {
    "repositories": TOOL_GH_REPOS,
    "code": TOOL_GH_CODE,
    "issues": TOOL_GH_ISSUES,
}

_CHART_TOOLS = {
    "bar": TOOL_CHART_BAR,
    "line": TOOL_CHART_LINE,
    "pie": TOOL_CHART_PIE,
    "scatter": TOOL_CHART_SCATTER,
    "area": TOOL_CHART_AREA,
    "column": TOOL_CHART_COLUMN,
}

_SQL_START_RE = re.compile(r"(?is)^(select|with)\b")
_SQL_FORBIDDEN_RE = re.compile(
    r"(?i)\b(?:insert|update|delete|drop|alter|attach|pragma|create)\b"
)
_SQL_REFUSAL = (
    "Requête refusée : seule une lecture SELECT ou WITH est autorisée "
    "(insert, update, delete, drop, alter, attach, pragma et create "
    "sont interdits)."
)

_SEGMENT = r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?"
_LIBRARY_ID = rf"(/{_SEGMENT}(?:/{_SEGMENT}){{1,2}})"
_LABELED_ID_RE = re.compile(
    rf"(?i)(?:context7-compatible\s+library\s+id|library\s+id)\s*:\s*{_LIBRARY_ID}"
)
_BARE_ID_RE = re.compile(rf"(?<![:\w/]){_LIBRARY_ID}")
_BARE_ID_ROOTS_SKIP = {
    "usr", "home", "tmp", "var", "etc", "opt", "bin", "lib", "proc",
    "workspace", "windows", "users",
}

_SECRET_RE = re.compile(
    r"(?i)(?:"
    r"ghp_[A-Za-z0-9]+|"
    r"github_pat_[A-Za-z0-9_]+|"
    r"sk-[A-Za-z0-9_\-]{8,}|"
    r"bearer\s+[A-Za-z0-9._\-]+|"
    r"(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+"
    r")"
)


def _clip(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    keep = _MAX_CHARS - len(_TRUNC_MARK)
    if keep < 1:
        return text[:_MAX_CHARS]
    return text[:keep] + _TRUNC_MARK


def _scrub(text: str) -> str:
    return _SECRET_RE.sub("[masqué]", text or "")


def _slice(total: float, attempts: int) -> float:
    """Per-call budget so retries stay inside the tool timeout."""
    if attempts <= 1:
        return total
    return max(1.0, (total - 1.0) / attempts)


def _reject_sql(sql: str) -> Optional[str]:
    text = (sql or "").replace("\ufeff", "").strip()
    if not _SQL_START_RE.match(text) or _SQL_FORBIDDEN_RE.search(text):
        return _SQL_REFUSAL
    return None


def _library_id_from(text: str, library: str) -> Optional[str]:
    """Pick a Context7 id (``/org/projet``) out of a resolve response."""
    labeled = [match.group(1) for match in _LABELED_ID_RE.finditer(text or "")]
    if labeled:
        found = labeled
    else:
        found = []
        for match in _BARE_ID_RE.finditer(text or ""):
            lib_id = match.group(1)
            root = lib_id.split("/", 2)[1].lower()
            if root in _BARE_ID_ROOTS_SKIP:
                continue
            found.append(lib_id)
    if not found:
        return None
    needle = (library or "").strip().strip("/").lower()
    if needle:
        for lib_id in found:
            if needle in lib_id.lower():
                return lib_id
    return found[0]


def _wants_repo_path(error: str) -> bool:
    text = (error or "").lower()
    if "repo_path" in text or "repository path" in text or "repo path" in text:
        return True
    return "required" in text and "path" in text


def _workspace_start() -> Path:
    try:
        from core.config import settings
    except Exception:
        return Path(os.getcwd()).resolve()
    try:
        return Path(settings.workspace_root).resolve()
    except Exception:
        return Path(os.getcwd()).resolve()


def _git_repo_path() -> str:
    """``LASME_MCP_GIT_REPO``, else a ``.git`` parent of the workspace.

    A relative override is joined to that same root (the git server is
    started the same way). An absolute override does not import config.
    """
    override = os.environ.get("LASME_MCP_GIT_REPO", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = _workspace_start() / path
        return str(path.resolve())
    start = _workspace_start()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return str(candidate)
    return str(start)


def _chart_payload(args: Dict[str, Any]) -> Dict[str, Any] | str:
    labels = args.get("labels")
    values = args.get("values")
    if not isinstance(labels, list) or not isinstance(values, list):
        return "Graphique refusé : labels et values doivent être des listes."
    if not labels or len(labels) != len(values):
        return (
            "Graphique refusé : labels et values doivent être non vides "
            "et de même longueur."
        )
    data = []
    for label, value in zip(labels, values, strict=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "Graphique refusé : values doit contenir uniquement des nombres."
        data.append({"category": str(label), "value": value})
    return {"title": str(args.get("title") or ""), "data": data}


def _server_ready(mcp_client: Optional[Any], server_id: str) -> bool:
    """True when the server may be offered. Does not start a process."""
    if mcp_client is not None:
        return bool(mcp_client.available(server_id))
    try:
        from core.mcp.catalog import configured_server_ids
    except ImportError:
        return False
    return server_id in configured_server_ids()


def _format_call(result: McpCallResult, server_id: str) -> str:
    if result.ok:
        return _clip(result.text or "")
    server = result.server or server_id
    error = _scrub(result.error or "erreur inconnue")
    return _clip(f"Outil indisponible ({server}) : {error}")


def register_mcp_stack(
    registry: ToolRegistry,
    *,
    mcp_client: Optional[Any] = None,
    model_id: str = "gemma-4-12b",
) -> None:
    """Register the MCP tools visible to ``model_id`` whose server is up."""
    allowed = tools_for_tier(model_tier(model_id))

    def _enabled(name: str, server_id: str) -> bool:
        return name in allowed and _server_ready(mcp_client, server_id)

    async def _raw(
        server_id: str,
        tool: str,
        arguments: Dict[str, Any],
        timeout_s: float,
    ) -> McpCallResult:
        client = mcp_client
        if client is None:
            try:
                from core.mcp.pool import get_mcp_client
            except ImportError:
                return McpCallResult(
                    ok=False,
                    server=server_id,
                    tool=tool,
                    error="client MCP absent",
                )
            try:
                client = get_mcp_client()
            except Exception as exc:
                return McpCallResult(
                    ok=False,
                    server=server_id,
                    tool=tool,
                    error=_scrub(f"{type(exc).__name__}: {exc}"),
                )
            if client is None:
                return McpCallResult(
                    ok=False,
                    server=server_id,
                    tool=tool,
                    error="client MCP absent",
                )
        try:
            return await client.call(
                server_id,
                tool,
                dict(arguments),
                timeout_s=timeout_s,
            )
        except Exception as exc:
            return McpCallResult(
                ok=False,
                server=server_id,
                tool=tool,
                error=_scrub(f"{type(exc).__name__}: {exc}"),
            )

    def _add(
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Any,
        *,
        category: str,
        timeout_s: float,
    ) -> None:
        registry.register(
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
                category=category,
                timeout_s=timeout_s,
                max_output_chars=_MAX_CHARS,
            )
        )

    if _enabled("library_docs", SERVER_CONTEXT7):
        async def _library_docs(args: Dict[str, Any]) -> str:
            library = str(args["library"]).strip()
            query = str(args["query"]).strip()
            per = _slice(_TIMEOUT_LIBRARY, 2)
            resolved = await _raw(
                SERVER_CONTEXT7,
                TOOL_C7_RESOLVE,
                {"libraryName": library, "query": query},
                per,
            )
            if not resolved.ok:
                return _format_call(resolved, SERVER_CONTEXT7)
            lib_id = _library_id_from(resolved.text or "", library)
            if not lib_id:
                return _clip(resolved.text or "")
            docs = await _raw(
                SERVER_CONTEXT7,
                TOOL_C7_DOCS,
                {"context7CompatibleLibraryID": lib_id, "topic": query},
                per,
            )
            return _format_call(docs, SERVER_CONTEXT7)

        _add(
            "library_docs",
            (
                "Serveur MCP Context7 : documentation à jour d'une "
                "bibliothèque (library, ex. fastapi) pour une question "
                "précise (query). Pour l'API d'une lib, pas pour les "
                "documents du projet (files_read_text) ni le dossier de "
                "travail (workspace_read)."
            ),
            {
                "type": "object",
                "properties": {
                    "library": {
                        "type": "string",
                        "description": "Nom de la bibliothèque, ex. fastapi",
                    },
                    "query": {
                        "type": "string",
                        "description": "Question précise sur l'API",
                    },
                },
                "required": ["library", "query"],
            },
            _library_docs,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_LIBRARY,
        )

    if _enabled("github_search", SERVER_GITHUB):
        async def _github_search(args: Dict[str, Any]) -> str:
            kind = str(args.get("kind") or "repositories")
            tool = _GH_KIND.get(kind, TOOL_GH_REPOS)
            result = await _raw(
                SERVER_GITHUB,
                tool,
                {"query": str(args["query"])},
                _TIMEOUT_GITHUB,
            )
            return _format_call(result, SERVER_GITHUB)

        _add(
            "github_search",
            (
                "Serveur MCP GitHub : recherche publique de dépôts, de "
                "code ou d'issues. kind = repositories (défaut), code "
                "ou issues."
            ),
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Requête GitHub"},
                    "kind": {
                        "type": "string",
                        "enum": ["repositories", "code", "issues"],
                        "description": "Défaut : repositories",
                    },
                },
                "required": ["query"],
            },
            _github_search,
            category=CATEGORY_NETWORK,
            timeout_s=_TIMEOUT_GITHUB,
        )

    if _enabled("github_read_file", SERVER_GITHUB):
        async def _github_read_file(args: Dict[str, Any]) -> str:
            payload = {
                "owner": str(args["owner"]),
                "repo": str(args["repo"]),
                "path": str(args["path"]),
            }
            per = _slice(_TIMEOUT_GITHUB, 2)
            result = await _raw(SERVER_GITHUB, TOOL_GH_FILE, payload, per)
            if not result.ok:
                result = await _raw(SERVER_GITHUB, TOOL_GH_FILE, payload, per)
            return _format_call(result, SERVER_GITHUB)

        _add(
            "github_read_file",
            (
                "Serveur MCP GitHub : lit un fichier d'un dépôt distant "
                "(owner, repo, path). Distinct de files_read_text "
                "(documents importés du projet) et de workspace_read "
                "(dossier de travail MCP)."
            ),
            {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string", "description": "Chemin dans le dépôt"},
                },
                "required": ["owner", "repo", "path"],
            },
            _github_read_file,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_GITHUB,
        )

    if _enabled("repo_status", SERVER_GIT):
        async def _repo_status(args: Dict[str, Any]) -> str:
            action = str(args.get("action") or "status")
            remote = _GIT_ACTIONS.get(action)
            if remote is None:
                return (
                    "Action refusée : repo_status est en lecture seule "
                    "(status, log ou diff)."
                )
            payload: Dict[str, Any] = {}
            if action == "log" and args.get("max_count") is not None:
                payload["max_count"] = int(args["max_count"])
            per = _slice(_TIMEOUT_GIT, 2)
            result = await _raw(SERVER_GIT, remote, payload, per)
            if not result.ok and _wants_repo_path(result.error or ""):
                retry = dict(payload)
                retry["repo_path"] = _git_repo_path()
                result = await _raw(SERVER_GIT, remote, retry, per)
            return _format_call(result, SERVER_GIT)

        _add(
            "repo_status",
            (
                "Serveur MCP Git, lecture seule : status, log ou diff du "
                "dépôt de travail. Ne commit pas. Pour lire un fichier du "
                "dossier MCP, workspace_read ; pour pandas ou matplotlib, "
                "python_run."
            ),
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "log", "diff"],
                        "description": "Défaut : status",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "Nombre de commits pour log",
                    },
                },
                "required": [],
            },
            _repo_status,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_GIT,
        )

    if _enabled("workspace_list", SERVER_FS):
        async def _workspace_list(args: Dict[str, Any]) -> str:
            path = args.get("path")
            if not isinstance(path, str) or not path.strip():
                path = "."
            result = await _raw(
                SERVER_FS,
                TOOL_FS_LIST,
                {"path": path},
                _TIMEOUT_FS,
            )
            return _format_call(result, SERVER_FS)

        _add(
            "workspace_list",
            (
                "Serveur MCP filesystem : liste un dossier du répertoire "
                "de travail MCP (path relatif, défaut .). Pas files_list "
                "(fichiers importés du projet)."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif, défaut .",
                    },
                },
                "required": [],
            },
            _workspace_list,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_FS,
        )

    if _enabled("workspace_read", SERVER_FS):
        async def _workspace_read(args: Dict[str, Any]) -> str:
            payload: Dict[str, Any] = {"path": str(args["path"])}
            if args.get("head") is not None:
                payload["head"] = int(args["head"])
            result = await _raw(SERVER_FS, TOOL_FS_READ, payload, _TIMEOUT_FS)
            return _format_call(result, SERVER_FS)

        _add(
            "workspace_read",
            (
                "Serveur MCP filesystem : lit un fichier texte du dossier "
                "de travail MCP (path, head optionnel en nombre de lignes). "
                "Pour un document importé, files_read_text. Pour une "
                "analyse pandas ou matplotlib, python_run."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "head": {
                        "type": "integer",
                        "description": "Ne garder que les N premières lignes",
                    },
                },
                "required": ["path"],
            },
            _workspace_read,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_FS,
        )

    if _enabled("workspace_search", SERVER_FS):
        async def _workspace_search(args: Dict[str, Any]) -> str:
            raw_pattern = args.get("pattern")
            raw_query = args.get("query")
            pattern = ""
            if isinstance(raw_pattern, str) and raw_pattern.strip():
                pattern = raw_pattern.strip()
            elif isinstance(raw_query, str) and raw_query.strip():
                pattern = raw_query.strip()
            if not pattern:
                return "Motif manquant : indique pattern ou query."
            directory = args.get("path")
            if not isinstance(directory, str) or not directory.strip():
                directory = "."
            result = await _raw(
                SERVER_FS,
                TOOL_FS_SEARCH,
                {"path": directory, "pattern": pattern},
                _TIMEOUT_FS,
            )
            return _format_call(result, SERVER_FS)

        _add(
            "workspace_search",
            (
                "Serveur MCP filesystem : cherche un motif (pattern ou "
                "query) dans le dossier de travail MCP. Pas rag_search "
                "ni files_read_text (documents du projet), ni python_run."
            ),
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Motif (glob)"},
                    "query": {
                        "type": "string",
                        "description": "Alias de pattern",
                    },
                },
                "required": [],
            },
            _workspace_search,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_FS,
        )

    if _enabled("query_data", SERVER_SQLITE):
        async def _query_data(args: Dict[str, Any]) -> str:
            sql = str(args["sql"])
            refused = _reject_sql(sql)
            if refused:
                return refused
            per = _slice(_TIMEOUT_SQL, 2)
            result = await _raw(
                SERVER_SQLITE, TOOL_SQL_READ, {"query": sql}, per
            )
            if not result.ok:
                result = await _raw(
                    SERVER_SQLITE, TOOL_SQL_READ, {"sql": sql}, per
                )
            return _format_call(result, SERVER_SQLITE)

        _add(
            "query_data",
            (
                "Serveur MCP SQLite : exécute une requête SELECT ou WITH "
                "en lecture seule. Pour une analyse pandas ou un graphique "
                "matplotlib, python_run."
            ),
            {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "Requête SELECT ou WITH uniquement",
                    },
                },
                "required": ["sql"],
            },
            _query_data,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_SQL,
        )

    if _enabled("render_chart", SERVER_CHART):
        async def _render_chart(args: Dict[str, Any]) -> str:
            remote = _CHART_TOOLS.get(str(args.get("chart") or ""))
            if remote is None:
                return "Graphique refusé : type inconnu."
            built = _chart_payload(args)
            if isinstance(built, str):
                return built
            per = _slice(_TIMEOUT_CHART, 2)
            result = await _raw(SERVER_CHART, remote, built, per)
            if not result.ok:
                result = await _raw(SERVER_CHART, remote, built, per)
            return _format_call(result, SERVER_CHART)

        _add(
            "render_chart",
            (
                "Serveur MCP AntV : graphique bar, line, pie, scatter, "
                "area ou column à partir de labels et values. Retourne "
                "le texte du serveur (souvent une URL d'image). Pour une "
                "figure matplotlib dans le bac à sable, python_run "
                "(fichiers sous /workspace)."
            ),
            {
                "type": "object",
                "properties": {
                    "chart": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "scatter", "area", "column"],
                    },
                    "title": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "values": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["chart", "title", "labels", "values"],
            },
            _render_chart,
            category=CATEGORY_EXEC,
            timeout_s=_TIMEOUT_CHART,
        )

    if _enabled("convert_time", SERVER_TIME):
        async def _convert_time(args: Dict[str, Any]) -> str:
            moment = str(args["time"])
            source = str(args["from_timezone"])
            target = str(args["to_timezone"])
            per = _slice(_TIMEOUT_TIME, 2)
            result = await _raw(
                SERVER_TIME,
                TOOL_TIME_CONVERT,
                {
                    "source_timezone": source,
                    "target_timezone": target,
                    "time": moment,
                },
                per,
            )
            if not result.ok:
                result = await _raw(
                    SERVER_TIME,
                    TOOL_TIME_CONVERT,
                    {
                        "from_timezone": source,
                        "to_timezone": target,
                        "time": moment,
                    },
                    per,
                )
            return _format_call(result, SERVER_TIME)

        _add(
            "convert_time",
            (
                "Serveur MCP Time : convertit une heure (time) entre deux "
                "fuseaux IANA (from_timezone, to_timezone), par exemple "
                "Europe/Paris vers America/New_York."
            ),
            {
                "type": "object",
                "properties": {
                    "time": {"type": "string", "description": "Heure à convertir"},
                    "from_timezone": {
                        "type": "string",
                        "description": "Fuseau IANA source, ex. Europe/Paris",
                    },
                    "to_timezone": {
                        "type": "string",
                        "description": "Fuseau IANA cible, ex. America/New_York",
                    },
                },
                "required": ["time", "from_timezone", "to_timezone"],
            },
            _convert_time,
            category=CATEGORY_READ,
            timeout_s=_TIMEOUT_TIME,
        )
