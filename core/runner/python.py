from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNTIME_ROOT = Path(__file__).resolve().parents[2] / ".runtime" / "runner"
MAX_CAPTURE_CHARS = 80_000
MAX_OUTPUT_FILES = 32
MAX_OUTPUT_FILE_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_TOTAL_BYTES = 64 * 1024 * 1024
SAFE_OUTPUT_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$")


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
    """Run untrusted Python in a short-lived, networkless Docker container."""

    def __init__(
        self,
        *,
        root: Path = RUNTIME_ROOT,
        image: str = "lasme-python-runner:latest",
    ):
        self.root = Path(root).resolve()
        self.image = image
        self.docker_command = _resolve_docker_command()
        self.root.mkdir(parents=True, exist_ok=True)

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

    def _job_directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid runner job id.")
        path = (self.root / job_id).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid runner job path.")
        return path

    def output_path(self, job_id: str, filename: str) -> Optional[Path]:
        if not SAFE_OUTPUT_NAME.fullmatch(Path(filename).name):
            return None
        try:
            output_root = (self._job_directory(job_id) / "output").resolve()
        except ValueError:
            return None
        path = (output_root / Path(filename).name).resolve()
        if output_root not in path.parents or not path.is_file():
            return None
        return path

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

    async def run(
        self,
        code: str,
        *,
        timeout_seconds: int = 15,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> PythonRunResult:
        if not await self.available():
            raise RuntimeError(
                "The isolated Python runner image is not installed."
            )
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

    def cleanup(self, *, max_age_seconds: int = 86_400) -> int:
        cutoff = time.time() - max_age_seconds
        removed = 0
        for job_dir in self.root.iterdir():
            if (
                job_dir.is_dir()
                and re.fullmatch(r"[a-f0-9]{32}", job_dir.name)
                and job_dir.stat().st_mtime < cutoff
            ):
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
        return removed


python_runner = PythonRunner()
