"""Lifecycle supervisor for llama-server in router mode.

Responsibilities:
- resolve the llama-server executable (env override, then known paths);
- render the router preset from the runtime profiles and launch the
  process with logs and a pid file under ``.runtime/llama/``;
- health polling, idempotent start (reuse a healthy server), restart;
- scrape the Prometheus ``/metrics`` endpoint per model.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from core.inference.preset import write_preset
from core.inference.profiles import (
    RUNTIME_PROFILES,
    RuntimeProfile,
    resident_profiles,
)

_KNOWN_SERVER_PATHS = [
    Path.home() / "llama.cpp" / "build" / "bin" / "Release" / "llama-server.exe",
    Path(__file__).resolve().parent.parent.parent
    / "llama.cpp"
    / "build"
    / "bin"
    / "Release"
    / "llama-server.exe",
]


def resolve_server_executable(configured: str = "") -> Optional[Path]:
    """Find llama-server: explicit setting > known paths > PATH."""
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate
    for candidate in _KNOWN_SERVER_PATHS:
        if candidate.is_file():
            return candidate
    found = shutil.which("llama-server")
    return Path(found) if found else None


@dataclass
class SupervisorStatus:
    running: bool
    healthy: bool
    pid: Optional[int]
    base_url: str
    executable: Optional[str]
    preset_path: Optional[str]
    details: Dict[str, Any] = field(default_factory=dict)


class LlamaServerSupervisor:
    """Manage the llama-server router process for this application."""

    def __init__(
        self,
        runtime_root: Optional[Path] = None,
        vram_total_mib: Optional[int] = None,
    ):
        self.runtime_root = Path(
            runtime_root
            or (Path(__file__).resolve().parent.parent.parent / ".runtime" / "llama")
        )
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.preset_path = self.runtime_root / "router_models.ini"
        self.log_path = self.runtime_root / "llama-server.log"
        self.pid_path = self.runtime_root / "server.pid"
        self._process: Optional[subprocess.Popen] = None
        self._vram_total_mib = vram_total_mib

    # ------------------------------------------------------------ helpers

    @property
    def base_url(self) -> str:
        return settings.llama_base_url.rstrip("/")

    def _profiles(self) -> List[RuntimeProfile]:
        """Resident profiles for the detected GPU + on-demand ones."""
        residents = resident_profiles(self._vram_total_mib)
        resident_ids = {p.id for p in residents}
        on_demand = [p for p in RUNTIME_PROFILES.values() if p.id not in resident_ids]
        return [*residents, *on_demand]

    def _read_pid(self) -> Optional[int]:
        try:
            return int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return None

    def _write_pid(self, pid: int) -> None:
        self.pid_path.write_text(str(pid), encoding="utf-8")

    def tail_log(self, lines: int = 20) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(content.splitlines()[-lines:])
        except OSError:
            return ""

    # -------------------------------------------------------------- checks

    async def is_healthy(self) -> bool:
        try:
            resp = await httpx.AsyncClient(trust_env=False, timeout=3.0).get(
                f"{self.base_url}/health"
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def status(self) -> SupervisorStatus:
        pid = self._read_pid()
        executable = resolve_server_executable(settings.llama_server_path)
        healthy = await self.is_healthy()
        return SupervisorStatus(
            running=healthy or (self._process is not None and self._process.poll() is None),
            healthy=healthy,
            pid=pid,
            base_url=self.base_url,
            executable=str(executable) if executable else None,
            preset_path=str(self.preset_path) if self.preset_path.exists() else None,
            details={"log_tail": self.tail_log(5)} if not healthy else {},
        )

    # ------------------------------------------------------------ control

    async def start(self) -> SupervisorStatus:
        """Launch the router (no-op if already healthy). Idempotent."""
        if await self.is_healthy():
            return await self.status()

        executable = resolve_server_executable(settings.llama_server_path)
        if executable is None:
            raise FileNotFoundError(
                "llama-server introuvable : définissez LLAMA_SERVER_PATH "
                "ou installez llama.cpp (build avec CUDA)."
            )

        profiles = self._profiles()
        write_preset(self.preset_path, profiles)

        command = [
            str(executable),
            "--models-preset", str(self.preset_path),
            "--models-max", str(settings.llama_models_max),
            "--jinja",
            "--host", settings.llama_host,
            "--port", str(settings.llama_port),
        ]
        log_handle = self.log_path.open("ab")
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            self._process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(self.runtime_root),
                creationflags=creationflags,
            )
        finally:
            # The child keeps its own inherited handle; the parent copy
            # must not stay open (it would lock the log file).
            log_handle.close()
        self._write_pid(self._process.pid)

        deadline = time.monotonic() + settings.llama_startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"llama-server s'est arrêté (code {self._process.returncode}). "
                    f"Fin de journal :\n{self.tail_log(30)}"
                )
            if await self.is_healthy():
                return await self.status()
            time.sleep(1.0)
        raise TimeoutError(
            f"llama-server n'a pas répondu en {settings.llama_startup_timeout}s. "
            f"Fin de journal :\n{self.tail_log(30)}"
        )

    async def stop(self) -> bool:
        """Stop the router and its model child processes."""
        pid = self._read_pid()
        stopped = False
        if pid is not None:
            # /T kills the whole tree: router + per-model instances.
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
            stopped = result.returncode == 0
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            stopped = True
        if not stopped:
            # Fallback for a server started outside this process.
            result = subprocess.run(
                ["taskkill", "/IM", "llama-server.exe", "/T", "/F"],
                capture_output=True,
                text=True,
            )
            stopped = result.returncode == 0
        self.pid_path.unlink(missing_ok=True)
        return stopped

    async def ensure_running(self) -> SupervisorStatus:
        """Restart the router if it drifted away (crash, manual kill)."""
        if await self.is_healthy():
            return await self.status()
        return await self.start()

    # ------------------------------------------------------------ metrics

    async def metrics(self, model_id: str) -> Dict[str, float]:
        """Scrape llama-server Prometheus metrics for one routed model."""
        try:
            resp = await httpx.AsyncClient(trust_env=False, timeout=5.0).get(
                f"{self.base_url}/metrics",
                params={"model": model_id},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return {}
        values: Dict[str, float] = {}
        for line in resp.text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, raw = line.rpartition(" ")
            try:
                values[name] = float(raw)
            except ValueError:
                continue
        return values
