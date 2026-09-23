"""Pool stdio MCP paresseux. Une session ouverte par serveur, un appel à la fois.

Le process n'est lancé qu'au premier ``call``. Aucune valeur d'environnement
n'est journalisée.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TextIO

from core.mcp.catalog import build_catalog
from core.mcp.types import McpCallResult, McpServerSpec
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents

_BASE_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOME",
    "LANG",
)
_ERROR_LIMIT = 200

_CLIENT: StdioMcpPool | None = None
_GUARD = threading.Lock()


def _child_env(extra: Mapping[str, str]) -> dict[str, str]:
    """Base minimale plus ``spec.env``. ``NODE_OPTIONS`` n'est jamais copié.

    Le client stdio du SDK y ajoute son propre sous-ensemble sûr, jamais
    ``os.environ`` entier.
    """
    env: dict[str, str] = {}
    for key in _BASE_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key, value in extra.items():
        if key.upper() == "NODE_OPTIONS":
            continue
        env[key] = value
    env.pop("NODE_OPTIONS", None)
    return env


def _coerce_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return 45.0
    if timeout != timeout or timeout == float("inf"):
        return 45.0
    if timeout <= 0:
        return 0.001
    return timeout


def _redact(text: str, secrets: Sequence[str]) -> str:
    cleaned = " ".join(text.split())
    for secret in secrets:
        if len(secret) >= 6 and secret in cleaned:
            cleaned = cleaned.replace(secret, "***")
    if len(cleaned) > _ERROR_LIMIT:
        return cleaned[:_ERROR_LIMIT] + "…"
    return cleaned


def _consume_future_error(fut: asyncio.Future[object]) -> None:
    with suppress(asyncio.CancelledError, asyncio.InvalidStateError):
        fut.exception()


def _block_text(block: object) -> str | None:
    if isinstance(block, TextContent):
        return block.text
    if isinstance(block, EmbeddedResource) and isinstance(block.resource, TextResourceContents):
        return block.resource.text
    return None


def _flatten(result: CallToolResult, server_id: str, tool: str) -> McpCallResult:
    parts = [_block_text(block) for block in result.content]
    text = "\n".join(part for part in parts if part is not None)
    if result.isError:
        return McpCallResult(
            ok=False,
            text=text,
            server=server_id,
            tool=tool,
            error=text or "erreur outil",
        )
    return McpCallResult(ok=True, text=text, server=server_id, tool=tool)


@dataclass
class _Job:
    tool: str
    arguments: dict[str, Any]
    timeout_s: float
    future: asyncio.Future[CallToolResult]


class _Worker:
    """Garde la session dans la tâche qui a ouvert les scopes anyio."""

    def __init__(self, spec: McpServerSpec, errlog: TextIO, timeout_s: float) -> None:
        self.spec = spec
        self._errlog = errlog
        self._timeout_s = timeout_s
        self.queue: asyncio.Queue[_Job | None] = asyncio.Queue()
        self.started = asyncio.Event()
        self.start_error: BaseException | None = None
        self.task: asyncio.Task[None] | None = None

    def spawn(self) -> None:
        self.task = asyncio.create_task(self._run(), name=f"mcp-{self.spec.id}")

    async def _run(self) -> None:
        ready = False
        try:
            params = StdioServerParameters(
                command=self.spec.command,
                args=list(self.spec.args),
                env=_child_env(self.spec.env),
                cwd=self.spec.cwd,
            )
            async with stdio_client(params, errlog=self._errlog) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self._timeout_s),
                ) as session:
                    await session.initialize()
                    ready = True
                    self.started.set()
                    await self._serve(session)
        except Exception as exc:
            if not ready:
                self.start_error = exc
        finally:
            if not self.started.is_set():
                self.started.set()
            self._fail_queued(self.start_error or RuntimeError("session fermée"))

    async def _serve(self, session: ClientSession) -> None:
        while True:
            job = await self.queue.get()
            if job is None:
                return
            try:
                result = await session.call_tool(
                    job.tool,
                    arguments=job.arguments,
                    read_timeout_seconds=timedelta(seconds=job.timeout_s),
                )
            except McpError as exc:
                _reject(job, exc)
            except RuntimeError as exc:
                _reject(job, exc)
            except Exception as exc:
                _reject(job, exc)
                return
            else:
                if not job.future.done():
                    job.future.set_result(result)

    def _fail_queued(self, exc: BaseException) -> None:
        while True:
            try:
                job = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if job is not None:
                _reject(job, exc)


def _reject(job: _Job, exc: BaseException) -> None:
    if job.future.done():
        return
    job.future.set_exception(exc)


class StdioMcpPool:
    """Client MCP stdio. ``call`` retourne toujours un :class:`McpCallResult`."""

    def __init__(self, specs: Sequence[McpServerSpec]) -> None:
        self._specs = {spec.id: spec for spec in specs}
        self._locks = {spec.id: asyncio.Lock() for spec in specs}
        self._workers: dict[str, _Worker] = {}
        self._down: set[str] = set()
        self._closed = False
        self._errlog: TextIO | None = None

    def available(self, server_id: str) -> bool:
        """True si le serveur est configuré et n'a pas échoué au démarrage."""
        return not self._closed and server_id in self._specs and server_id not in self._down

    async def call(
        self,
        server_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float = 45.0,
    ) -> McpCallResult:
        """Appelle un outil. Une panne n'est pas une exception."""
        try:
            return await self._call(server_id, tool, arguments, timeout_s=timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._failure(server_id, tool, self._safe("appel impossible", exc))

    async def aclose(self) -> None:
        """Ferme les sessions et les process encore ouverts."""
        self._closed = True
        for server_id in list(self._locks):
            async with self._locks[server_id]:
                await self._stop_worker(server_id)
        if self._errlog is not None:
            self._errlog.close()
            self._errlog = None

    async def _call(
        self,
        server_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> McpCallResult:
        if self._closed:
            return self._failure(server_id, tool, "pool fermé")
        spec = self._specs.get(server_id)
        if spec is None:
            return self._failure(server_id, tool, "serveur inconnu")
        if server_id in self._down:
            return self._failure(server_id, tool, "serveur indisponible")
        try:
            payload = dict(arguments)
        except Exception:
            return self._failure(server_id, tool, "arguments invalides")
        timeout = _coerce_timeout(timeout_s)
        async with self._locks[server_id]:
            if self._closed:
                return self._failure(server_id, tool, "pool fermé")
            if server_id in self._down:
                return self._failure(server_id, tool, "serveur indisponible")
            try:
                worker = await self._ensure_worker(spec, timeout)
            except Exception as exc:
                self._down.add(server_id)
                await self._stop_worker(server_id)
                return self._failure(server_id, tool, self._safe("démarrage impossible", exc))
            future: asyncio.Future[CallToolResult] = asyncio.get_running_loop().create_future()
            future.add_done_callback(_consume_future_error)
            await worker.queue.put(_Job(tool, payload, timeout, future))
            try:
                outcome = await asyncio.wait_for(asyncio.shield(future), timeout=timeout + 1)
            except TimeoutError:
                await self._cancel_worker(server_id)
                return self._failure(server_id, tool, "appel impossible (TimeoutError)")
            except Exception as exc:
                if worker.task is None or worker.task.done():
                    await self._stop_worker(server_id)
                return self._failure(server_id, tool, self._safe("appel impossible", exc))
            return _flatten(outcome, server_id, tool)

    async def _ensure_worker(self, spec: McpServerSpec, timeout_s: float) -> _Worker:
        current = self._workers.get(spec.id)
        if (
            current is not None
            and current.task is not None
            and not current.task.done()
            and current.start_error is None
            and current.started.is_set()
        ):
            return current
        if current is not None:
            await self._stop_worker(spec.id)
        worker = _Worker(spec, self._errlog_handle(), timeout_s)
        self._workers[spec.id] = worker
        worker.spawn()
        try:
            await asyncio.wait_for(worker.started.wait(), timeout=timeout_s)
        except TimeoutError:
            await self._cancel_worker(spec.id)
            raise TimeoutError("démarrage trop long") from None
        if worker.start_error is not None or worker.task is None or worker.task.done():
            exc = worker.start_error or RuntimeError("démarrage interrompu")
            await self._stop_worker(spec.id)
            raise exc
        return worker

    async def _cancel_worker(self, server_id: str) -> None:
        worker = self._workers.pop(server_id, None)
        if worker is None or worker.task is None:
            return
        if not worker.task.done():
            worker.task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await worker.task

    async def _stop_worker(self, server_id: str) -> None:
        worker = self._workers.pop(server_id, None)
        if worker is None or worker.task is None:
            return
        if not worker.task.done():
            await worker.queue.put(None)
            with suppress(Exception):
                await worker.task
        elif worker.task.cancelled():
            return
        else:
            with suppress(Exception):
                worker.task.exception()

    def _errlog_handle(self) -> TextIO:
        if self._errlog is None or self._errlog.closed:
            self._errlog = open(os.devnull, "w", encoding="utf-8")
        return self._errlog

    def _secrets(self) -> tuple[str, ...]:
        found: list[str] = []
        for spec in self._specs.values():
            for value in spec.env.values():
                if isinstance(value, str) and len(value) >= 6:
                    found.append(value)
        return tuple(found)

    def _safe(self, prefix: str, exc: BaseException) -> str:
        detail = _redact(f"{type(exc).__name__}: {exc}", self._secrets())
        if not detail:
            return prefix
        return f"{prefix} ({detail})"

    @staticmethod
    def _failure(server_id: str, tool: str, error: str) -> McpCallResult:
        return McpCallResult(ok=False, server=server_id, tool=tool, error=error)


def get_mcp_client() -> StdioMcpPool:
    """Pool partagé, construit avec :func:`build_catalog` au premier appel."""
    global _CLIENT
    with _GUARD:
        if _CLIENT is None:
            _CLIENT = StdioMcpPool(build_catalog())
        return _CLIENT


def reset_mcp_client_for_tests() -> None:
    """Oublie le singleton et ferme le pool précédent si la boucle le permet."""
    global _CLIENT
    with _GUARD:
        client = _CLIENT
        _CLIENT = None
    if client is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(client.aclose())
        return
    loop.create_task(client.aclose())
