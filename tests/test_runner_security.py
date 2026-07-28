import asyncio
import tempfile
import unittest
from pathlib import Path

from core.runner.python import (
    MAX_CAPTURE_CHARS,
    MAX_OUTPUT_FILES,
    MAX_OUTPUT_TOTAL_BYTES,
    PythonRunner,
)


class RunnerResourceSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdout_capture_keeps_only_a_bounded_tail(self):
        reader = asyncio.StreamReader()
        payload = b"x" * (2 * 1024 * 1024) + b"END"
        reader.feed_data(payload)
        reader.feed_eof()

        captured = await PythonRunner._read_stream_tail(reader)

        self.assertLessEqual(len(captured), MAX_CAPTURE_CHARS)
        self.assertTrue(captured.endswith(b"END"))

    async def test_output_collection_caps_count_and_total_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = PythonRunner(root=root / "runner")
            output = root / "output"
            output.mkdir()
            for index in range(100):
                (output / f"result-{index:03d}.txt").write_bytes(
                    b"x" * 1024
                )

            files = runner._collect_output_files(output, "a" * 32)

            self.assertLessEqual(len(files), MAX_OUTPUT_FILES)
            self.assertLessEqual(
                sum(item["size_bytes"] for item in files),
                MAX_OUTPUT_TOTAL_BYTES,
            )
            self.assertEqual(
                len(list(output.glob("result-*.txt"))),
                MAX_OUTPUT_FILES,
            )


class RunnerImageSecurityTests(unittest.TestCase):
    def test_runner_image_uses_a_non_root_user(self):
        dockerfile = (
            Path(__file__).resolve().parents[1]
            / "infra"
            / "runner"
            / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn("USER runner", dockerfile)
        self.assertIn("uid 10001", dockerfile)


if __name__ == "__main__":
    unittest.main()
