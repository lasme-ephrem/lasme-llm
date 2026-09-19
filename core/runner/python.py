from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / ".runtime" / "runner"
MAX_CAPTURE_CHARS = 80_000
MAX_OUTPUT_FILES = 32
MAX_OUTPUT_FILE_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_TOTAL_BYTES = 64 * 1024 * 1024
SAFE_OUTPUT_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$")

# Warm pool: one long-lived hardened container; jobs run via `docker exec`
# inside fresh per-job subdirectories of the mounted host workspace.
POOL_ENV_FLAG = "LASME_RUNNER_POOL"
POOL_CONTAINER_NAME = "lasme-runner-pool"
POOL_IDLE_SECONDS = 120.0
POOL_IMAGE_MISSING_MESSAGE = "The isolated Python runner image is not installed."
# PID 1 of the pool container. Unlike `sleep infinity`, this init reaps the
# zombie processes the sweeper creates when it SIGKILLs workload strays
# (they are re-parented to PID 1); without reaping, the pids-limit would
# slowly leak. It exits on SIGTERM/SIGKILL like any default-handled process.
POOL_INIT_PROGRAM = (
    "import os, time\n"
    "while True:\n"
    "    try:\n"
    "        os.waitpid(-1, os.WNOHANG)\n"
    "    except ChildProcessError:\n"
    "        pass\n"
    "    time.sleep(0.5)\n"
)
# Runs after every job inside the same exec: the cold path destroyed the whole
# container, so no workload process could outlive it. The pool keeps the
# container alive, so stray processes are SIGKILLed instead. PID 1 of the PID
# namespace ignores SIGKILL; the sweeper also skips itself and its parent (the
# `sh` wrapper that must still `exit $st`). Workload orphans are re-parented
# to PID 1, so they are all covered.
POOL_SWEEP_PROGRAM = (
    "import os, signal\n"
    "me = os.getpid()\n"
    "parent = os.getppid()\n"
    "for entry in os.listdir(\"/proc\"):\n"
    "    if not entry.isdigit():\n"
    "        continue\n"
    "    pid = int(entry)\n"
    "    if pid in (1, me, parent):\n"
    "        continue\n"
    "    try:\n"
    "        os.kill(pid, signal.SIGKILL)\n"
    "    except OSError:\n"
    "        pass\n"
)


def _env_flag_disabled(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def _resolve_docker_command() -> str:
    configured = os.getenv("LASME_DOCKER_BINARY", "").strip()
    if configured:
        return configured
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    if os.name == "nt":
        local_app_data = Path(
            os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        candidates = (
            local_app_data
            / "Programs"
            / "DockerDesktop"
            / "resources"
            / "bin"
            / "docker.exe",
            Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return "docker"


@dataclass
class PythonRunResult:
    job_id: str
    status: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    files: List[Dict[str, Any]]

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


class PythonRunner:
    """Run untrusted Python in a short-lived, networkless Docker container.

    Two execution paths share the same public API and the same hardening
    flags: the historical cold path (one `docker run` per job) and a warm
    pool path (one persistent hardened container, jobs via `docker exec`).
    Set LASME_RUNNER_POOL=0 to force the cold path.
    """

    def __init__(
        self,
        *,
        root: Path = RUNTIME_ROOT,
        image: str = "lasme-python-runner:latest",
        pool_idle_seconds: float = POOL_IDLE_SECONDS,
    ):
        self.root = Path(root).resolve()
        self.image = image
        self.docker_command = _resolve_docker_command()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool_workspace = (
            self.root.parent / "runner_pool" / "workspace"
        ).resolve()
        self.pool_workspace.mkdir(parents=True, exist_ok=True)
        self.pool_idle_seconds = max(0.0, float(pool_idle_seconds))
        # Injectable spawn hook (tests substitute a fake process factory).
        self._spawn_process = asyncio.create_subprocess_exec
        # Injectable sync removal hook used by the reaper thread and stop().
        self._rm_force_sync = self._rm_force_sync_impl
        self._pool_job_lock: Optional[asyncio.Lock] = None
        self._pool_job_lock_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pool_state_lock = threading.Lock()
        self._pool_state: Dict[str, Any] = {
            "running": False,
            "job_active": False,
            "last_used": 0.0,
        }
        self._reaper_thread: Optional[threading.Thread] = None
        self._reaper_started = False
        self._pool_stop_event = threading.Event()

    async def available(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                self.docker_command,
                "image",
                "inspect",
                self.image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return await asyncio.wait_for(process.wait(), timeout=4.0) == 0
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            return False

    def _pool_enabled(self) -> bool:
        return not _env_flag_disabled(os.getenv(POOL_ENV_FLAG))

    async def ensure_running(self) -> bool:
        """Make sure the runner is usable; boots the warm pool container."""
        if not await self.available():
            return False
        if self._pool_enabled():
            await self._ensure_pool_running()
        return True

    def _job_directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid runner job id.")
        path = (self.root / job_id).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid runner job path.")
        return path

    def _pool_job_directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid runner job id.")
        path = (self.pool_workspace / job_id).resolve()
        if self.pool_workspace not in path.parents:
            raise ValueError("Invalid runner job path.")
        return path

    def _output_path_in(
        self,
        validate: Callable[[str], Path],
        job_id: str,
        filename: str,
    ) -> Optional[Path]:
        if not SAFE_OUTPUT_NAME.fullmatch(Path(filename).name):
            return None
        try:
            output_root = (validate(job_id) / "output").resolve()
        except ValueError:
            return None
        path = (output_root / Path(filename).name).resolve()
        if output_root not in path.parents or not path.is_file():
            return None
        return path

    def output_path(self, job_id: str, filename: str) -> Optional[Path]:
        resolved = self._output_path_in(self._job_directory, job_id, filename)
        if resolved is not None:
            return resolved
        return self._output_path_in(
            self._pool_job_directory, job_id, filename
        )

    async def _force_remove_container(self, container_name: str) -> None:
        """Best-effort hard stop so a timed-out workload cannot keep running."""
        try:
            cleanup = await asyncio.create_subprocess_exec(
                self.docker_command,
                "rm",
                "--force",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(cleanup.wait(), timeout=6.0)
            except asyncio.TimeoutError:
                try:
                    cleanup.kill()
                except ProcessLookupError:
                    pass
                await cleanup.wait()
        except (FileNotFoundError, OSError):
            return

    @staticmethod
    async def _read_stream_tail(
        stream: Optional[asyncio.StreamReader],
        *,
        limit: int = MAX_CAPTURE_CHARS,
    ) -> bytes:
        if stream is None:
            return b""
        tail = bytearray()
        while True:
            chunk = await stream.read(16_384)
            if not chunk:
                break
            tail.extend(chunk)
            if len(tail) > limit:
                del tail[:-limit]
        return bytes(tail)

    def _collect_output_files(
        self,
        output_dir: Path,
        job_id: str,
    ) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        total_output_bytes = 0
        for path in sorted(output_dir.iterdir()):
            if not path.is_file() or not SAFE_OUTPUT_NAME.fullmatch(path.name):
                continue
            size = path.stat().st_size
            if (
                size > MAX_OUTPUT_FILE_BYTES
                or len(files) >= MAX_OUTPUT_FILES
                or total_output_bytes + size > MAX_OUTPUT_TOTAL_BYTES
            ):
                path.unlink(missing_ok=True)
                continue
            total_output_bytes += size
            files.append(
                {
                    "name": path.name,
                    "size_bytes": size,
                    "url": f"/api/runner/jobs/{job_id}/files/{path.name}",
                }
            )
        return files

    async def _run_cold(
        self,
        code: str,
        *,
        timeout_seconds: int = 15,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> PythonRunResult:
        if not await self.available():
            raise RuntimeError(POOL_IMAGE_MISSING_MESSAGE)
        job_id = uuid.uuid4().hex
        job_dir = self._job_directory(job_id)
        output_dir = job_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=False)
        script_path = job_dir / "main.py"
        input_path = job_dir / "input.json"
        script_path.write_text(code, encoding="utf-8")
        input_path.write_text(
            json.dumps(inputs or {}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            script_path.chmod(0o444)
            input_path.chmod(0o444)
            output_dir.chmod(0o777)
        except OSError:
            pass
        timeout_seconds = max(1, min(int(timeout_seconds), 20))
        started = time.monotonic()
        script_mount = str(script_path).replace("\\", "/")
        input_mount = str(input_path).replace("\\", "/")
        output_mount = str(output_dir).replace("\\", "/")
        container_name = f"lasme-runner-{job_id}"
        command = [
            self.docker_command,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--memory",
            "768m",
            "--memory-swap",
            "768m",
            "--cpus",
            "1.5",
            "--pids-limit",
            "96",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m,mode=1777",
            "--mount",
            (
                f"type=bind,src={script_mount},"
                "dst=/workspace/main.py,readonly"
            ),
            "--mount",
            (
                f"type=bind,src={input_mount},"
                "dst=/workspace/input.json,readonly"
            ),
            "--mount",
            (
                f"type=bind,src={output_mount},"
                "dst=/workspace/output"
            ),
            "--workdir",
            "/workspace",
            "-e",
            "LASME_INPUT_FILE=/workspace/input.json",
            "-e",
            "LASME_OUTPUT_DIR=/workspace/output",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-e",
            "PYTHONUNBUFFERED=1",
            self.image,
            "python",
            "-I",
            "-B",
            "/workspace/main.py",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        stdout_task = asyncio.create_task(
            self._read_stream_tail(process.stdout)
        )
        stderr_task = asyncio.create_task(
            self._read_stream_tail(process.stderr)
        )
        timed_out = False
        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=float(timeout_seconds),
            )
        except asyncio.TimeoutError:
            timed_out = True
            try:
                await self._force_remove_container(container_name)
            finally:
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        stdout_bytes, stderr_bytes = await asyncio.gather(
            stdout_task,
            stderr_task,
        )
        duration_ms = round((time.monotonic() - started) * 1_000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")[-MAX_CAPTURE_CHARS:]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[-MAX_CAPTURE_CHARS:]
        if timed_out:
            stderr = (
                f"Execution stopped after {timeout_seconds} seconds.\n{stderr}"
            ).strip()
        files = self._collect_output_files(output_dir, job_id)
        return PythonRunResult(
            job_id=job_id,
            status=(
                "timeout"
                if timed_out
                else ("success" if process.returncode == 0 else "error")
            ),
            exit_code=None if timed_out else process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            files=files,
        )

    # ------------------------------------------------------------------
    # Warm pool path
    # ------------------------------------------------------------------

    def _job_lock_for_current_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._pool_job_lock is None or self._pool_job_lock_loop is not loop:
            self._pool_job_lock = asyncio.Lock()
            self._pool_job_lock_loop = loop
        return self._pool_job_lock

    def _mark_pool_state(self, **changes: Any) -> None:
        with self._pool_state_lock:
            self._pool_state.update(changes)

    async def _rm_force_async(self, container_name: str) -> None:
        try:
            process = await self._spawn_process(
                self.docker_command,
                "rm",
                "--force",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ},
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=6.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        except (FileNotFoundError, OSError):
            return

    def _rm_force_sync_impl(self, container_name: str) -> None:
        try:
            subprocess.run(
                [self.docker_command, "rm", "--force", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10.0,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return

    async def _probe_pool_running(self) -> bool:
        try:
            process = await self._spawn_process(
                self.docker_command,
                "container",
                "inspect",
                "-f",
                "{{.State.Running}}",
                POOL_CONTAINER_NAME,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ},
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
                return False
            if process.returncode != 0 or process.stdout is None:
                return False
            state = await process.stdout.read()
            return b"true" in state.lower()
        except (FileNotFoundError, OSError):
            return False

    async def _start_pool_container(self) -> None:
        """Start the persistent container with the exact cold-path flags."""
        workspace_mount = str(self.pool_workspace).replace("\\", "/")
        command = [
            self.docker_command,
            "run",
            "-d",
            "--name",
            POOL_CONTAINER_NAME,
            "--network",
            "none",
            "--memory",
            "768m",
            "--memory-swap",
            "768m",
            "--cpus",
            "1.5",
            "--pids-limit",
            "96",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m,mode=1777",
            "--mount",
            f"type=bind,src={workspace_mount},dst=/workspace",
            "--workdir",
            "/workspace",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-e",
            "PYTHONUNBUFFERED=1",
            self.image,
            "python",
            "-I",
            "-B",
            "-c",
            POOL_INIT_PROGRAM,
        ]
        process = await self._spawn_process(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        stderr_task = asyncio.create_task(
            self._read_stream_tail(process.stderr, limit=2_000)
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        if process.returncode != 0:
            stderr_bytes = await stderr_task
            detail = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Failed to start the pooled Python runner container."
                + (f" {detail}" if detail else "")
            )

    async def _ensure_pool_running(self) -> None:
        with self._pool_state_lock:
            if self._pool_state["running"]:
                return
        if await self._probe_pool_running():
            self._mark_pool_state(
                running=True, last_used=time.monotonic()
            )
            self._ensure_reaper()
            return
        # Remove any stale/exited container, then (re)create it hardened.
        await self._rm_force_async(POOL_CONTAINER_NAME)
        await self._start_pool_container()
        self._mark_pool_state(running=True, last_used=time.monotonic())
        self._ensure_reaper()

    def _ensure_reaper(self) -> None:
        with self._pool_state_lock:
            if self._reaper_started and (
                self._reaper_thread is not None
                and self._reaper_thread.is_alive()
            ):
                return
            self._reaper_started = True
        self._pool_stop_event.clear()
        self._reaper_thread = threading.Thread(
            target=self._reaper_loop,
            name="lasme-runner-pool-reaper",
            daemon=True,
        )
        self._reaper_thread.start()

    def _reaper_loop(self) -> None:
        while not self._pool_stop_event.is_set():
            with self._pool_state_lock:
                running = self._pool_state["running"]
                job_active = self._pool_state["job_active"]
                last_used = self._pool_state["last_used"]
            if not running or job_active:
                self._pool_stop_event.wait(0.25)
                continue
            idle_for = time.monotonic() - last_used
            if idle_for >= self.pool_idle_seconds:
                self._reap_pool_sync()
                continue
            remaining = max(0.02, self.pool_idle_seconds - idle_for)
            self._pool_stop_event.wait(min(1.0, remaining))

    def _reap_pool_sync(self) -> None:
        with self._pool_state_lock:
            if self._pool_state["job_active"] or not self._pool_state["running"]:
                return
            self._pool_state["running"] = False
        try:
            self._rm_force_sync(POOL_CONTAINER_NAME)
        except (FileNotFoundError, OSError):
            return

    @staticmethod
    def _force_remove_tree(path: Path) -> None:
        try:
            shutil.rmtree(path)
        except OSError:
            # Windows: read-only files (chmod 0o444) block deletion.
            for child in path.rglob("*"):
                try:
                    child.chmod(0o666)
                except OSError:
                    pass
            try:
                path.chmod(0o666)
            except OSError:
                pass
            shutil.rmtree(path, ignore_errors=True)

    def _job_exec_command(self, job_id: str) -> List[str]:
        """One `docker exec` per job: run the script, then sweep strays.

        The `sh -c` wrapper preserves the script's exit code while killing
        any process the workload left behind, mirroring the cold path where
        the whole container was destroyed after every job. The sweep output
        is discarded and cannot alter the captured streams' meaning.
        """
        container_job_dir = f"/workspace/{job_id}"
        inner = (
            f"python -I -B {container_job_dir}/main.py; "
            "st=$?; "
            f"python -I -B -c '{POOL_SWEEP_PROGRAM}' >/dev/null 2>&1; "
            "exit $st"
        )
        return [
            self.docker_command,
            "exec",
            "-e",
            f"LASME_INPUT_FILE={container_job_dir}/input.json",
            "-e",
            f"LASME_OUTPUT_DIR={container_job_dir}/output",
            "-w",
            container_job_dir,
            POOL_CONTAINER_NAME,
            "sh",
            "-c",
            inner,
        ]

    async def _exec_job(
        self,
        command: List[str],
        *,
        timeout_seconds: int,
    ) -> tuple[asyncio.subprocess.Process, bytes, bytes, bool]:
        """Run one exec; returns (process, stdout, stderr, timed_out)."""
        process = await self._spawn_process(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        stdout_task = asyncio.create_task(
            self._read_stream_tail(process.stdout)
        )
        stderr_task = asyncio.create_task(
            self._read_stream_tail(process.stderr)
        )
        timed_out = False
        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=float(timeout_seconds),
            )
        except asyncio.TimeoutError:
            timed_out = True
            # Same hard guarantee as the cold path: a timed-out workload
            # cannot keep running. Destroying the pool container kills the
            # exec'd process; the next job transparently recreates it.
            await self._rm_force_async(POOL_CONTAINER_NAME)
            self._mark_pool_state(running=False)
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        stdout_bytes, stderr_bytes = await asyncio.gather(
            stdout_task,
            stderr_task,
        )
        return process, stdout_bytes, stderr_bytes, timed_out

    async def _run_pooled(
        self,
        code: str,
        *,
        timeout_seconds: int = 15,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> PythonRunResult:
        started = time.monotonic()
        if not await self.available():
            raise RuntimeError(POOL_IMAGE_MISSING_MESSAGE)
        timeout_seconds = max(1, min(int(timeout_seconds), 20))
        job_id = uuid.uuid4().hex
        lock = self._job_lock_for_current_loop()
        async with lock:
            job_dir = self._pool_job_directory(job_id)
            output_dir = job_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=False)
            script_path = job_dir / "main.py"
            input_path = job_dir / "input.json"
            script_path.write_text(code, encoding="utf-8")
            input_path.write_text(
                json.dumps(inputs or {}, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                script_path.chmod(0o444)
                input_path.chmod(0o444)
                output_dir.chmod(0o777)
            except OSError:
                pass
            command = self._job_exec_command(job_id)
            self._mark_pool_state(
                job_active=True, last_used=time.monotonic()
            )
            timed_out = False
            files: List[Dict[str, Any]] = []
            try:
                attempt = 0
                while True:
                    await self._ensure_pool_running()
                    process, stdout_bytes, stderr_bytes, timed_out = (
                        await self._exec_job(
                            command,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    if timed_out:
                        break
                    # Exit code 125 means the docker daemon itself failed,
                    # e.g. the container died out-of-band (Docker Desktop
                    # restart, manual removal). Recreate it and retry the
                    # job once before reporting an error.
                    if process.returncode == 125 and attempt == 0:
                        attempt += 1
                        self._mark_pool_state(running=False)
                        await self._rm_force_async(POOL_CONTAINER_NAME)
                        continue
                    break
                duration_ms = round((time.monotonic() - started) * 1_000)
                stdout = stdout_bytes.decode(
                    "utf-8", errors="replace"
                )[-MAX_CAPTURE_CHARS:]
                stderr = stderr_bytes.decode(
                    "utf-8", errors="replace"
                )[-MAX_CAPTURE_CHARS:]
                if timed_out:
                    stderr = (
                        "Execution stopped after "
                        f"{timeout_seconds} seconds.\n{stderr}"
                    ).strip()
                files = self._collect_output_files(output_dir, job_id)
            finally:
                self._force_remove_tree(job_dir)
                self._mark_pool_state(
                    job_active=False, last_used=time.monotonic()
                )
        return PythonRunResult(
            job_id=job_id,
            status=(
                "timeout"
                if timed_out
                else ("success" if process.returncode == 0 else "error")
            ),
            exit_code=None if timed_out else process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            files=files,
        )

    async def run(
        self,
        code: str,
        *,
        timeout_seconds: int = 15,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> PythonRunResult:
        if self._pool_enabled():
            return await self._run_pooled(
                code,
                timeout_seconds=timeout_seconds,
                inputs=inputs,
            )
        return await self._run_cold(
            code,
            timeout_seconds=timeout_seconds,
            inputs=inputs,
        )

    def stop(self) -> None:
        """Explicitly stop the reaper thread and destroy the pool container."""
        self._pool_stop_event.set()
        reaper = self._reaper_thread
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=2.0)
        with self._pool_state_lock:
            was_running = self._pool_state["running"]
            self._pool_state["running"] = False
        if was_running:
            try:
                self._rm_force_sync(POOL_CONTAINER_NAME)
            except (FileNotFoundError, OSError):
                return

    def cleanup(self, *, max_age_seconds: int = 86_400) -> int:
        cutoff = time.time() - max_age_seconds
        removed = 0
        for base in (self.root, self.pool_workspace):
            if not base.is_dir():
                continue
            for job_dir in base.iterdir():
                if (
                    job_dir.is_dir()
                    and re.fullmatch(r"[a-f0-9]{32}", job_dir.name)
                    and job_dir.stat().st_mtime < cutoff
                ):
                    self._force_remove_tree(job_dir)
                    removed += 1
        return removed


python_runner = PythonRunner()
