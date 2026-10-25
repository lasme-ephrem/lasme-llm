import asyncio
import contextlib
import io
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from core.runner.python import (
    POOL_CONTAINER_NAME,
    POOL_SWEEP_PROGRAM,
    PythonRunResult,
    PythonRunner,
)

JOB_DIR_PATTERN = re.compile(r"/workspace/([0-9a-f]{32})/main\.py")


def make_runner(temp_dir: Path, **kwargs) -> PythonRunner:
    return PythonRunner(root=temp_dir / "runner", **kwargs)


class FakeProcess:
    def __init__(self, argv, *, stdout=b"", stderr=b"", returncode=0):
        self.argv = [str(part) for part in argv]
        self._exit_code = returncode
        self.returncode = None
        self.kill_count = 0
        stdout_reader = asyncio.StreamReader()
        stdout_reader.feed_data(stdout)
        stdout_reader.feed_eof()
        stderr_reader = asyncio.StreamReader()
        stderr_reader.feed_data(stderr)
        stderr_reader.feed_eof()
        self.stdout = stdout_reader
        self.stderr = stderr_reader

    async def wait(self):
        await asyncio.sleep(0)
        self.returncode = self._exit_code
        return self.returncode

    def kill(self):
        self.kill_count += 1
        self._exit_code = -9


class HangingProcess(FakeProcess):
    """A process whose wait() never returns until kill() is called."""

    def __init__(self, argv, **kwargs):
        super().__init__(argv, **kwargs)
        self._released = asyncio.Event()

    async def wait(self):
        await self._released.wait()
        self.returncode = self._exit_code
        return self.returncode

    def kill(self):
        self.kill_count += 1
        self._exit_code = -9
        self._released.set()


class PoolHarness:
    """Fake docker binary: executes job scripts for real, in-process."""

    def __init__(self, runner: PythonRunner):
        self.runner = runner
        self.log: list[list[str]] = []
        self.container_running = False
        self.rm_calls: list[list[str]] = []
        self._image_available = True
        runner._spawn_process = self.spawn
        runner._rm_force_sync = self.rm_force_sync

        async def available() -> bool:
            return self._image_available

        runner.available = available  # type: ignore[method-assign]

    def rm_force_sync(self, container_name: str) -> None:
        self.rm_calls.append(["docker", "rm", "--force", container_name])
        self.container_running = False

    async def spawn(self, *argv, **kwargs):
        parts = [str(part) for part in argv]
        self.log.append(parts)
        if parts[1:3] == ["image", "inspect"]:
            return FakeProcess(
                argv, returncode=0 if self._image_available else 1
            )
        if parts[1:3] == ["container", "inspect"]:
            if self.container_running:
                return FakeProcess(argv, stdout=b"true\n", returncode=0)
            return FakeProcess(argv, returncode=1)
        if parts[1:2] == ["run"]:
            self.container_running = True
            return FakeProcess(argv, returncode=0)
        if parts[1:2] == ["rm"]:
            self.container_running = False
            return FakeProcess(argv, returncode=0)
        if parts[1:2] == ["exec"]:
            inner = parts[-1]
            if JOB_DIR_PATTERN.search(inner):
                if not self.container_running:
                    return FakeProcess(
                        argv,
                        stderr=(
                            b"Error response from daemon: Container "
                            b"lasme-runner-pool is not running\n"
                        ),
                        returncode=125,
                    )
                return self._execute_job_script(argv, inner)
            return FakeProcess(argv, returncode=0)
        return FakeProcess(argv, returncode=0)

    def _execute_job_script(self, argv, inner: str) -> FakeProcess:
        match = JOB_DIR_PATTERN.search(inner)
        job_id = match.group(1)
        job_dir = self.runner.pool_workspace / job_id
        if not (job_dir / "main.py").is_file():
            return FakeProcess(
                argv,
                stderr=b"python: can't open file: No such file or directory\n",
                returncode=2,
            )
        code_text = (job_dir / "main.py").read_text(encoding="utf-8")
        buffer = io.StringIO()
        error_buffer = io.StringIO()
        exit_code = 0
        saved_env = {
            key: os.environ.get(key)
            for key in ("LASME_INPUT_FILE", "LASME_OUTPUT_DIR")
        }
        os.environ["LASME_INPUT_FILE"] = str(job_dir / "input.json")
        os.environ["LASME_OUTPUT_DIR"] = str(job_dir / "output")
        try:
            with contextlib.redirect_stdout(
                buffer
            ), contextlib.redirect_stderr(error_buffer):
                exec(
                    compile(code_text, "main.py", "exec"),
                    {"__name__": "__main__"},
                )
        except BaseException as exc:  # noqa: BLE001 - mirrors python -I
            error_buffer.write(f"{type(exc).__name__}: {exc}\n")
            exit_code = 1
        finally:
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return FakeProcess(
            argv,
            stdout=buffer.getvalue().encode("utf-8"),
            stderr=error_buffer.getvalue().encode("utf-8"),
            returncode=exit_code,
        )

    def run_commands(self) -> list[list[str]]:
        return [parts for parts in self.log if parts[1:2] == ["run"]]

    def exec_commands(self) -> list[list[str]]:
        return [
            parts
            for parts in self.log
            if parts[1:2] == ["exec"] and JOB_DIR_PATTERN.search(parts[-1])
        ]

    def rm_async_commands(self) -> list[list[str]]:
        return [parts for parts in self.log if parts[1:2] == ["rm"]]


class PoolLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.temp_dir = Path(self._tmp.name)
        patcher = mock.patch.dict(os.environ, {"LASME_RUNNER_POOL": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_first_job_boots_hardened_container_and_second_reuses_it(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        first = await runner.run("print(7 * 1234)")
        second = await runner.run("print('second')")

        self.assertEqual(first.status, "success")
        self.assertIn("8638", first.stdout)
        self.assertEqual(second.status, "success")
        self.assertIn("second", second.stdout)
        # Exactly one container boot, shared by both jobs.
        self.assertEqual(len(harness.run_commands()), 1)
        self.assertEqual(len(harness.exec_commands()), 2)

    async def test_pool_container_started_with_the_exact_hardening_flags(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        await runner.run("print(1)")

        run_command = harness.run_commands()[0]
        self.assertIn("lasme-runner-pool", run_command)
        self.assertIn("lasme-python-runner:latest", run_command)
        self.assertIn("--network", run_command)
        self.assertEqual(run_command[run_command.index("--network") + 1], "none")
        self.assertEqual(
            run_command[run_command.index("--memory") + 1], "768m"
        )
        self.assertEqual(
            run_command[run_command.index("--memory-swap") + 1], "768m"
        )
        self.assertEqual(run_command[run_command.index("--cpus") + 1], "1.5")
        self.assertEqual(
            run_command[run_command.index("--pids-limit") + 1], "96"
        )
        self.assertIn("--read-only", run_command)
        self.assertIn("--cap-drop", run_command)
        self.assertEqual(
            run_command[run_command.index("--cap-drop") + 1], "ALL"
        )
        self.assertIn("--security-opt", run_command)
        self.assertEqual(
            run_command[run_command.index("--security-opt") + 1],
            "no-new-privileges",
        )
        tmpfs = run_command[run_command.index("--tmpfs") + 1]
        for token in ("noexec", "nosuid", "size=128m", "mode=1777"):
            self.assertIn(token, tmpfs)
        mount = run_command[run_command.index("--mount") + 1]
        self.assertIn("type=bind,", mount)
        self.assertIn("dst=/workspace", mount)
        self.assertIn(
            str(runner.pool_workspace).replace("\\", "/"), mount
        )
        # PID 1 is a zombie-reaping init, not a bare sleep.
        tail = run_command[run_command.index("lasme-python-runner:latest") + 1:]
        self.assertEqual(tail[0], "python")
        self.assertEqual(tail[1], "-I")
        self.assertEqual(tail[3], "-c")
        self.assertIn("waitpid", tail[4])

    async def test_exec_runs_isolated_python_against_the_job_directory(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        result = await runner.run("print('hello')", inputs={"k": 1})

        exec_command = harness.exec_commands()[0]
        self.assertIn(POOL_CONTAINER_NAME, exec_command)
        self.assertEqual(exec_command[-3], "sh")
        self.assertEqual(exec_command[-2], "-c")
        inner = exec_command[-1]
        self.assertIn(
            f"python -I -B /workspace/{result.job_id}/main.py", inner
        )
        # The post-job sweep mirrors the cold path's container destruction.
        self.assertIn(POOL_SWEEP_PROGRAM, inner)
        self.assertIn("exit $st", inner)
        self.assertIn("-w", exec_command)
        self.assertIn(f"/workspace/{result.job_id}", exec_command)
        env_flags = [
            exec_command[index + 1]
            for index, part in enumerate(exec_command)
            if part == "-e"
        ]
        self.assertTrue(
            any(
                flag == f"LASME_INPUT_FILE=/workspace/{result.job_id}/input.json"
                for flag in env_flags
            )
        )
        self.assertTrue(
            any(
                flag == f"LASME_OUTPUT_DIR=/workspace/{result.job_id}/output"
                for flag in env_flags
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)

    async def test_job_directory_is_reset_between_jobs(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        first = await runner.run(
            "import os\n"
            "open(os.path.join(os.environ['LASME_OUTPUT_DIR'], "
            "'x.txt'), 'w').write('a')\n"
            "print('first done')\n"
        )
        self.assertEqual(first.status, "success")
        # The output file was collected host-side before the reset.
        self.assertEqual([item["name"] for item in first.files], ["x.txt"])
        self.assertFalse((runner.pool_workspace / first.job_id).exists())

        second = await runner.run("print('after reset')")

        self.assertEqual(second.status, "success")
        self.assertEqual([item["name"] for item in second.files], [])
        self.assertFalse((runner.pool_workspace / second.job_id).exists())
        # Nothing leaked from the first job into the pool workspace.
        self.assertEqual(list(runner.pool_workspace.iterdir()), [])

    async def test_dead_container_is_recreated(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        await runner.run("print(1)")
        self.assertTrue(harness.container_running)
        # The container dies out-of-band (Docker restart, manual removal...).
        harness.container_running = False

        result = await runner.run("print(2)")

        # The exec failed with docker's "container not running" (125), the
        # runner recreated the hardened container and retried the job.
        self.assertEqual(result.status, "success")
        self.assertIn("2", result.stdout)
        self.assertEqual(len(harness.run_commands()), 2)
        self.assertGreaterEqual(len(harness.exec_commands()), 2)
        self.assertIn(["rm", "--force", POOL_CONTAINER_NAME],
                      [parts[1:4] for parts in harness.rm_async_commands()])

    async def test_exited_container_is_removed_before_recreation(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)
        original_spawn = harness.spawn

        async def spawn(*argv, **kwargs):
            parts = [str(part) for part in argv]
            if parts[1:3] == ["container", "inspect"]:
                reader = asyncio.StreamReader()
                reader.feed_data(b"false\n")
                reader.feed_eof()
                probe = FakeProcess(argv, returncode=0)
                probe.stdout = reader
                return probe
            return await original_spawn(*argv, **kwargs)

        runner._spawn_process = spawn

        result = await runner.run("print(1)")

        self.assertEqual(result.status, "success")
        rm_calls = harness.rm_async_commands()
        self.assertEqual(len(rm_calls), 1)
        self.assertEqual(rm_calls[0][2:4], ["--force", POOL_CONTAINER_NAME])
        self.assertEqual(len(harness.run_commands()), 1)

    async def test_timeout_destroys_the_pool_container(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)
        original_spawn = harness.spawn

        async def spawn(*argv, **kwargs):
            parts = [str(part) for part in argv]
            if (
                parts[1:2] == ["exec"]
                and JOB_DIR_PATTERN.search(parts[-1])
            ):
                harness.log.append(parts)
                return HangingProcess(argv)
            return await original_spawn(*argv, **kwargs)

        runner._spawn_process = spawn

        result = await runner.run("print(1)", timeout_seconds=1)

        self.assertEqual(result.status, "timeout")
        self.assertIsNone(result.exit_code)
        self.assertIn("Execution stopped after 1 seconds", result.stderr)
        # The hard guarantee: the container hosting the runaway exec is gone.
        self.assertFalse(harness.container_running)
        self.assertIn(
            ["rm", "--force", POOL_CONTAINER_NAME],
            [parts[1:4] for parts in harness.rm_async_commands()],
        )
        # The job directory was still cleaned up.
        self.assertFalse((runner.pool_workspace / result.job_id).exists())

    async def test_idle_reaper_destroys_the_container(self):
        runner = make_runner(self.temp_dir, pool_idle_seconds=0.05)
        harness = PoolHarness(runner)

        await runner.run("print(1)")
        self.assertTrue(harness.container_running)

        async def wait_for_reap() -> bool:
            for _ in range(200):
                if harness.rm_calls:
                    return True
                await asyncio.sleep(0.05)
            return False

        self.assertTrue(await wait_for_reap())
        self.assertEqual(
            harness.rm_calls[-1],
            ["docker", "rm", "--force", POOL_CONTAINER_NAME],
        )
        self.assertFalse(harness.container_running)

        runner.stop()

    async def test_stop_destroys_the_container_immediately(self):
        runner = make_runner(self.temp_dir, pool_idle_seconds=3_600.0)
        harness = PoolHarness(runner)

        await runner.run("print(1)")
        self.assertTrue(harness.container_running)

        runner.stop()

        self.assertEqual(
            harness.rm_calls[-1],
            ["docker", "rm", "--force", POOL_CONTAINER_NAME],
        )
        self.assertFalse(harness.container_running)

    async def test_kill_switch_routes_back_to_the_cold_path(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)
        cold_calls: list[str] = []

        async def fake_cold(code, *, timeout_seconds=15, inputs=None):
            cold_calls.append(code)
            return PythonRunResult(
                job_id=uuid.uuid4().hex,
                status="success",
                exit_code=0,
                stdout="cold",
                stderr="",
                duration_ms=1,
                files=[],
            )

        runner._run_cold = fake_cold

        with mock.patch.dict(os.environ, {"LASME_RUNNER_POOL": "0"}):
            result = await runner.run("print(1)")

        self.assertEqual(result.stdout, "cold")
        self.assertEqual(len(cold_calls), 1)
        # Nothing touched the pool: no container boot, no exec.
        self.assertEqual(harness.run_commands(), [])
        self.assertEqual(harness.exec_commands(), [])

        # Re-enable the flag: the pool path takes over again.
        result = await runner.run("print(2)")

        self.assertEqual(len(harness.run_commands()), 1)
        self.assertEqual(len(harness.exec_commands()), 1)

    async def test_concurrent_jobs_are_serialized_by_a_lock(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)
        original_exec = harness._execute_job_script
        active = {"count": 0, "violations": 0}

        def tracking_exec(argv, inner):
            active["count"] += 1
            if active["count"] > 1:
                active["violations"] += 1
            try:
                return original_exec(argv, inner)
            finally:
                active["count"] -= 1

        harness._execute_job_script = tracking_exec

        results = await asyncio.gather(
            runner.run("print('a')"),
            runner.run("print('b')"),
            runner.run("print('c')"),
        )

        self.assertEqual(active["violations"], 0)
        for result in results:
            self.assertEqual(result.status, "success")
        self.assertEqual(len(harness.exec_commands()), 3)

    async def test_output_path_resolves_pool_outputs(self):
        runner = make_runner(self.temp_dir)
        job_id = uuid.uuid4().hex
        output_dir = runner.pool_workspace / job_id / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "chart.png").write_bytes(b"png")

        resolved = runner.output_path(job_id, "chart.png")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "chart.png")
        self.assertIsNone(runner.output_path(job_id, "../escape.png"))
        self.assertIsNone(runner.output_path(uuid.uuid4().hex, "chart.png"))

    async def test_pooled_outputs_persist_after_workspace_reset_and_harvest_workdir(self):
        runner = make_runner(self.temp_dir)
        harness = PoolHarness(runner)
        self.addCleanup(runner.stop)

        result = await runner.run(
            "import os, pathlib\n"
            "open(os.path.join(os.environ['LASME_OUTPUT_DIR'], 'chart.png'), 'wb').write(b'PNGDATA')\n"
            "job_dir = pathlib.Path(os.environ['LASME_INPUT_FILE']).parent\n"
            "(job_dir / 'summary.csv').write_text('a,b\\n1,2\\n', encoding='utf-8')\n"
        )

        self.assertEqual(result.status, "success")
        names = [item["name"] for item in result.files]
        self.assertIn("chart.png", names)
        self.assertIn("summary.csv", names)
        # Pool workspace is completely clean after the job finishes.
        self.assertEqual(list(runner.pool_workspace.iterdir()), [])
        # Yet output_path still resolves the persisted files for HTTP serving.
        chart_path = runner.output_path(result.job_id, "chart.png")
        csv_path = runner.output_path(result.job_id, "summary.csv")
        self.assertIsNotNone(chart_path)
        self.assertEqual(chart_path.read_bytes(), b"PNGDATA")
        self.assertIsNotNone(csv_path)
        self.assertIn("a,b", csv_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(harness.exec_commands()), 1)


if __name__ == "__main__":
    unittest.main()
