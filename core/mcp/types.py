"""Contrat partagé du client MCP. Ne pas y mettre de réseau.

Les autres modules importent ces noms tels quels. Les identifiants de
serveurs et les noms d'outils distants sont figés ici pour que le
routeur, le catalogue et les façades restent alignés.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple


# --- identifiants de serveurs ------------------------------------------------

SERVER_EXA = "exa"
SERVER_BRAVE = "brave"
SERVER_TAVILY = "tavily"
SERVER_FETCH = "fetch"
SERVER_ARXIV = "arxiv"
SERVER_CONTEXT7 = "context7"
SERVER_GITHUB = "github"
SERVER_GIT = "git"
SERVER_FS = "filesystem"
SERVER_SQLITE = "sqlite"
SERVER_CHART = "chart"
SERVER_TIME = "time"
SERVER_FRESHNESS = "freshness"

# --- outils distants ---------------------------------------------------------

TOOL_EXA_SEARCH = "web_search_exa"
TOOL_EXA_FETCH = "web_fetch_exa"

TOOL_BRAVE_WEB = "brave_web_search"
TOOL_BRAVE_NEWS = "brave_news_search"

TOOL_TAVILY_SEARCH = "tavily_search"
TOOL_TAVILY_EXTRACT = "tavily_extract"

TOOL_FETCH = "fetch"

TOOL_ARXIV_SEARCH = "search_papers"

TOOL_C7_RESOLVE = "resolve-library-id"
TOOL_C7_DOCS = "get-library-docs"

TOOL_GH_REPOS = "search_repositories"
TOOL_GH_CODE = "search_code"
TOOL_GH_ISSUES = "search_issues"
TOOL_GH_FILE = "get_file_contents"

TOOL_GIT_STATUS = "git_status"
TOOL_GIT_LOG = "git_log"
TOOL_GIT_DIFF = "git_diff"

TOOL_FS_LIST = "list_directory"
TOOL_FS_READ = "read_text_file"
TOOL_FS_SEARCH = "search_files"

TOOL_SQL_READ = "read_query"
TOOL_SQL_TABLES = "list_tables"
TOOL_SQL_DESCRIBE = "describe_table"

TOOL_CHART_BAR = "generate_bar_chart"
TOOL_CHART_LINE = "generate_line_chart"
TOOL_CHART_PIE = "generate_pie_chart"
TOOL_CHART_SCATTER = "generate_scatter_chart"
TOOL_CHART_AREA = "generate_area_chart"
TOOL_CHART_COLUMN = "generate_column_chart"

TOOL_TIME_CONVERT = "convert_time"

TOOL_SPORTS = "sports_lookup"
TOOL_WEATHER = "weather_lookup"
TOOL_TECH_NEWS = "tech_news"
TOOL_WIKI = "wiki_lookup"


@dataclass(frozen=True)
class McpServerSpec:
    """Un serveur stdio. ``env`` ne contient que les variables ajoutées.

    ``command`` est un exécutable déjà résolu (chemin ou nom du PATH).
    Une spec n'est construite que si le serveur peut démarrer.
    """

    id: str
    title: str
    command: str
    args: Tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None


@dataclass
class McpCallResult:
    ok: bool
    text: str = ""
    server: str = ""
    tool: str = ""
    error: str = ""

    def for_parser(self) -> str:
        return self.text if self.ok else ""


class McpClient(Protocol):
    """Appel d'un outil distant. Les implémentations sont thread-safe par serveur."""

    async def call(
        self,
        server_id: str,
        tool: str,
        arguments: Dict[str, Any],
        *,
        timeout_s: float = 45.0,
    ) -> McpCallResult:
        """Retourne toujours un résultat. Une panne n'est pas une exception."""

    def available(self, server_id: str) -> bool:
        """True si le serveur est configuré et n'a pas été marqué indisponible."""


class ScriptedMcpClient:
    """Client de test. Clé = (server_id, tool). Valeur = texte ou McpCallResult.

    ``calls`` enregistre chaque invocation. Un outil absent répond ok=False.
    """

    def __init__(
        self,
        scripts: Optional[Mapping[Tuple[str, str], Any]] = None,
        *,
        available_servers: Optional[Tuple[str, ...]] = None,
    ) -> None:
        self.scripts = dict(scripts or {})
        self.calls: list[tuple[str, str, Dict[str, Any]]] = []
        self._available = available_servers

    def available(self, server_id: str) -> bool:
        if self._available is not None:
            return server_id in self._available
        return any(key[0] == server_id for key in self.scripts)

    async def call(
        self,
        server_id: str,
        tool: str,
        arguments: Dict[str, Any],
        *,
        timeout_s: float = 45.0,
    ) -> McpCallResult:
        del timeout_s
        self.calls.append((server_id, tool, dict(arguments)))
        scripted = self.scripts.get((server_id, tool))
        if scripted is None:
            return McpCallResult(
                ok=False,
                server=server_id,
                tool=tool,
                error=f"outil {tool} non scripté sur {server_id}",
            )
        if isinstance(scripted, McpCallResult):
            return scripted
        if isinstance(scripted, Exception):
            return McpCallResult(
                ok=False,
                server=server_id,
                tool=tool,
                error=f"{type(scripted).__name__}: {scripted}",
            )
        return McpCallResult(
            ok=True,
            text=str(scripted),
            server=server_id,
            tool=tool,
        )
