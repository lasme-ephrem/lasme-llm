import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from core.inference.client import LasmeLLMClient
from core.inference.preset import render_preset, write_preset
from core.inference.profiles import (
    FAST_MODEL,
    MAX_CONTEXT_MODEL,
    MINIMAL_MODEL,
    QUALITY_MODEL,
    RUNTIME_PROFILES,
    get_model_profile,
    resident_profiles,
    resolve_runtime_profile,
)
from core.inference import manager
from core.inference.supervisor import (
    LlamaServerSupervisor,
    resolve_server_executable,
)


class RuntimeProfileTests(unittest.TestCase):
    def test_legacy_aliases_map_to_v2_profiles(self):
        cases = {
            "gemma-4-chat": QUALITY_MODEL,
            "muse-glimmer:30b-q4_K_M-dflash": QUALITY_MODEL,
            "lasme-qwen-vision": QUALITY_MODEL,
            "gemma-4-fable": QUALITY_MODEL,
            "lasme-smol-fast": FAST_MODEL,
            "gemma-4-e4b": FAST_MODEL,
            "gemma-4-e2b": MINIMAL_MODEL,
            "gemma-4-12b-256k": MAX_CONTEXT_MODEL,
            "unknown-model": QUALITY_MODEL,
            None: QUALITY_MODEL,
        }
        for model, expected in cases.items():
            self.assertEqual(resolve_runtime_profile(model).id, expected, model)

    def test_preset_section_exposes_serving_keys(self):
        section = RUNTIME_PROFILES[MAX_CONTEXT_MODEL].preset_section()
        self.assertEqual(section["cache-type-k"], "q8_0")
        self.assertEqual(section["cache-type-v"], "q8_0")
        self.assertEqual(section["spec-type"], "draft-mtp")
        self.assertEqual(section["spec-draft-n-max"], 4)
        self.assertEqual(section["c"], 262_144)
        self.assertNotIn("load-on-startup", section)

        resident = RUNTIME_PROFILES[FAST_MODEL].preset_section()
        self.assertTrue(resident["load-on-startup"])
        self.assertNotIn("cache-type-k", resident)

    def test_resident_profiles_follow_vram_budget(self):
        big = resident_profiles(16_000)
        self.assertEqual([p.id for p in big], [FAST_MODEL, MINIMAL_MODEL])
        small = resident_profiles(8_000)
        self.assertEqual([p.id for p in small], [MINIMAL_MODEL])
        tiny = resident_profiles(4_000)
        self.assertEqual([p.id for p in tiny], [MINIMAL_MODEL])

    def test_legacy_model_profile_keeps_chat_tuning_shape(self):
        profile = get_model_profile("gemma-4-chat")
        for attribute in (
            "temperature", "num_ctx", "num_predict", "history_tokens",
            "system_addendum", "think", "keep_alive", "options",
        ):
            self.assertTrue(hasattr(profile, attribute))
        self.assertEqual(get_model_profile("lasme-smol-fast").num_ctx, 65_536)


class PresetTests(unittest.TestCase):
    def test_render_preset_contains_global_and_profile_sections(self):
        text = render_preset(RUNTIME_PROFILES.values())
        self.assertIn("version = 1", text)
        self.assertIn("[*]", text)
        self.assertIn("jinja = true", text)
        # dedup-cache-models is NOT emitted: b10358 rejects it.
        self.assertNotIn("dedup-cache-models", text)
        for profile_id in (QUALITY_MODEL, FAST_MODEL, MINIMAL_MODEL):
            self.assertIn(f"[{profile_id}]", text)
        self.assertIn(
            f"hf-repo = {RUNTIME_PROFILES[QUALITY_MODEL].hf_repo}", text
        )

    def test_write_preset_creates_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "router.ini"
            write_preset(path, [RUNTIME_PROFILES[FAST_MODEL]])
            self.assertTrue(path.is_file())
            self.assertIn(f"[{FAST_MODEL}]", path.read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _sse(payload):
    return "data: " + json.dumps(payload)


class LlamaClientTests(unittest.IsolatedAsyncioTestCase):
    def _client_with(self, *, stream_lines=None, response=None):
        client = LasmeLLMClient(base_url="http://llama.test")
        http = MagicMock()
        http.is_closed = False  # keep the client from replacing the mock
        if stream_lines is not None:
            http.stream.return_value = _FakeStream(stream_lines)
        else:
            http.post = AsyncMock(return_value=response)
            http.get = AsyncMock(return_value=response)
        client._http = http
        return client, http

    async def test_chat_routes_legacy_model_and_converts_response(self):
        openai_response = _FakeResponse({
            "model": "gemma-4-12b",
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Bonjour",
                    "reasoning_content": "je réfléchis",
                },
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        })
        client, http = self._client_with(response=openai_response)
        result = await client.chat(
            "gemma-4-chat",
            [{"role": "user", "content": "salut"}],
            think=False,
        )
        sent = http.post.call_args
        self.assertEqual(sent.args[0], "http://llama.test/v1/chat/completions")
        body = sent.kwargs["json"]
        self.assertEqual(body["model"], "gemma-4-12b")
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertTrue(body["stream"] is False)
        self.assertEqual(result["message"]["content"], "Bonjour")
        self.assertEqual(result["message"]["thinking"], "je réfléchis")
        self.assertEqual(result["eval_count"], 5)
        self.assertEqual(result["prompt_eval_count"], 12)
        self.assertEqual(result["done_reason"], "stop")
        self.assertTrue(result["done"])

    async def test_stream_chat_yields_ollama_shaped_chunks(self):
        lines = [
            _sse({"choices": [{"delta": {"role": "assistant"}}]}),
            _sse({"choices": [{"delta": {"reasoning_content": "hmm"}}]}),
            _sse({"choices": [{"delta": {"content": "Bon"}}]}),
            _sse({"choices": [{"delta": {"content": "jour"}}]}),
            _sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
            _sse({"usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
            "data: [DONE]",
        ]
        client, _ = self._client_with(stream_lines=lines)
        chunks = [
            chunk
            async for chunk in client.stream_chat(
                "lasme-smol-fast", [{"role": "user", "content": "salut"}]
            )
        ]
        self.assertEqual(chunks[0]["message"]["thinking"], "hmm")
        self.assertEqual(chunks[1]["message"]["content"], "Bon")
        self.assertEqual(chunks[2]["message"]["content"], "jour")
        final = chunks[-1]
        self.assertTrue(final["done"])
        self.assertEqual(final["done_reason"], "length")
        self.assertEqual(final["eval_count"], 3)
        self.assertEqual(final["prompt_eval_count"], 7)
        self.assertGreater(final["total_duration"], 0)

    async def test_stream_chat_surfaces_inference_errors(self):
        def boom(*args, **kwargs):
            raise OSError("connection refused")

        client = LasmeLLMClient(base_url="http://llama.test")
        http = MagicMock()
        http.is_closed = False
        http.stream.side_effect = boom
        client._http = http
        chunks = [
            c async for c in client.stream_chat("gemma-4-12b", [])
        ]
        self.assertEqual(chunks[0]["_error"], "OSError")
        self.assertTrue(chunks[0]["done"])

    async def test_list_models_is_ollama_shaped(self):
        client, http = self._client_with(
            response=_FakeResponse({"data": [
                {"id": "gemma-4-12b", "meta": {"size": 6_720_000_000}},
            ]})
        )
        models = await client.list_models()
        http.get.assert_called_once_with("http://llama.test/v1/models")
        self.assertEqual(models[0]["name"], "gemma-4-12b")
        self.assertEqual(models[0]["size"], 6_720_000_000)


class ManagerTests(unittest.TestCase):
    def test_scan_hf_cache_finds_gguf_repos(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = (
                root / "models--unsloth--gemma-4-E4B-it-qat-GGUF" / "snapshots" / "abc"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf").write_bytes(b"x" * 100)
            (snapshot / "mmproj-BF16.gguf").write_bytes(b"x" * 50)
            (snapshot / "mtp-gemma-4-E4B-it.gguf").write_bytes(b"x" * 10)
            (root / "models--ignore-me").mkdir()

            models = manager.scan_hf_cache(root)
            self.assertEqual(len(models), 1)
            model = models[0]
            self.assertEqual(model.repo_id, "unsloth/gemma-4-E4B-it-qat-GGUF")
            self.assertTrue(model.has_mmproj)
            self.assertTrue(model.has_mtp_drafter)
            self.assertEqual(model.total_bytes, 160)

    def test_detect_vram_parses_nvidia_smi_output(self):
        fake = MagicMock(stdout="16376\n", returncode=0)
        with mock.patch("subprocess.run", return_value=fake):
            self.assertEqual(manager.detect_vram_mib(), 16376)

    def test_detect_vram_returns_none_without_gpu(self):
        with mock.patch(
            "subprocess.run", side_effect=OSError("no nvidia-smi")
        ):
            self.assertIsNone(manager.detect_vram_mib())

    def test_is_profile_downloaded_matches_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "models--unsloth--gemma-4-E2B-it-qat-GGUF" / "snapshots" / "s"
            snapshot.mkdir(parents=True)
            (snapshot / "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf").write_bytes(b"x")
            self.assertTrue(
                manager.is_profile_downloaded(RUNTIME_PROFILES[MINIMAL_MODEL], root)
            )
            self.assertFalse(
                manager.is_profile_downloaded(RUNTIME_PROFILES[QUALITY_MODEL], root)
            )


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_executable_prefers_configured_path(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "llama-server.exe"
            fake.write_bytes(b"stub")
            self.assertEqual(resolve_server_executable(str(fake)), fake)
        with mock.patch(
            "core.inference.supervisor._KNOWN_SERVER_PATHS", []
        ), mock.patch("core.inference.supervisor.shutil.which", return_value=None):
            self.assertIsNone(resolve_server_executable("/inexistant/path"))

    async def test_start_is_idempotent_when_healthy(self):
        with tempfile.TemporaryDirectory() as temp:
            supervisor = LlamaServerSupervisor(runtime_root=Path(temp))
            with mock.patch.object(
                supervisor, "is_healthy", new=AsyncMock(return_value=True)
            ):
                status = await supervisor.start()
            self.assertTrue(status.healthy)
            # No preset/process work should happen on the fast path.
            self.assertFalse(supervisor.preset_path.exists())

    async def test_start_writes_preset_and_launches_process(self):
        with tempfile.TemporaryDirectory() as temp:
            supervisor = LlamaServerSupervisor(runtime_root=Path(temp))
            process = MagicMock()
            process.poll.return_value = None
            with mock.patch.object(
                supervisor,
                "is_healthy",
                new=AsyncMock(side_effect=[False, True, True]),
            ), mock.patch(
                "core.inference.supervisor.resolve_server_executable",
                return_value=Path("C:/fake/llama-server.exe"),
            ), mock.patch(
                "core.inference.supervisor.subprocess.Popen", return_value=process
            ) as popen:
                status = await supervisor.start()
            self.assertTrue(status.healthy)
            self.assertTrue(supervisor.preset_path.exists())
            self.assertIn(
                "--models-preset", popen.call_args.args[0]
            )
            preset_text = supervisor.preset_path.read_text(encoding="utf-8")
            self.assertIn("[gemma-4-12b]", preset_text)
            self.assertIn("[gemma-4-e4b]", preset_text)

    async def test_metrics_parses_prometheus_text(self):
        supervisor = LlamaServerSupervisor()
        fake = MagicMock()
        fake.status_code = 200
        fake.text = (
            "# HELP some help\n"
            "llamacpp:prompt_tokens_seconds 123.5\n"
            "llamacpp:predicted_tokens_seconds 210.25\n"
        )
        with mock.patch(
            "core.inference.supervisor.httpx.AsyncClient"
        ) as client_cls:
            client_cls.return_value.get = AsyncMock(return_value=fake)
            values = await supervisor.metrics("gemma-4-12b")
        self.assertEqual(values["llamacpp:prompt_tokens_seconds"], 123.5)
        self.assertEqual(values["llamacpp:predicted_tokens_seconds"], 210.25)


if __name__ == "__main__":
    unittest.main()
