"""OpenAI-compatible client for llama-server, with an Ollama-shaped facade.

The v2 runtime is llama-server (router mode). This client keeps the
exact public surface the existing chat server was built against —
``chat``/``stream_chat`` returning Ollama-style dicts — while speaking
``/v1/chat/completions`` under the hood. Model strings are resolved to
router profiles via ``resolve_runtime_profile`` so legacy names
(gemma-4-chat, lasme-smol-fast, muse-glimmer…) keep working.

Ollama chunk contract honored here (consumed by chat.server.main):
``message.content``, ``message.thinking``, ``done``, ``done_reason``,
``eval_count``, ``prompt_eval_count``, ``eval_duration``,
``prompt_eval_duration``, ``total_duration`` (nanoseconds), ``_error``.
"""

import json
import time
from typing import AsyncGenerator, Dict, List, Any, Optional, Union

import httpx

from core.config import settings
from core.inference.profiles import (
    ModelProfile,
    RUNTIME_PROFILES,
    get_model_profile,
    resolve_runtime_profile,
)

# llama-server accepts OpenAI reasoning hints; effort levels map from the
# legacy `think` parameter. "none" keeps short utility calls fast.
_THINK_TO_EFFORT = {
    False: "none",
    True: "default",
    None: "default",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "high",
}


class LasmeLLMClient:
    """Facade over llama-server's OpenAI-compatible chat API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.llama_base_url).rstrip("/")
        self._http: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0),
                trust_env=False,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    # ------------------------------------------------------------ helpers

    def _build_payload(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: Optional[float],
        num_predict: Optional[int],
        options: Optional[Dict[str, Any]],
        think: Optional[Union[bool, str]],
        stream: bool,
        stream_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = get_model_profile(model)
        runtime = resolve_runtime_profile(model)
        sampling: Dict[str, Any] = {
            "top_p": profile.options.get("top_p", 0.95),
            "top_k": profile.options.get("top_k", 64),
        }
        if options:
            for key in ("top_p", "top_k", "repeat_penalty", "repeat_last_n"):
                if key in options:
                    sampling[key] = options[key]

        effort = _THINK_TO_EFFORT.get(think, "default")
        payload: Dict[str, Any] = {
            "model": runtime.id,
            "messages": messages,
            "stream": stream,
            "temperature": (
                profile.temperature if temperature is None else temperature
            ),
            "max_tokens": num_predict or profile.num_predict,
            **sampling,
        }
        if effort != "default":
            payload["reasoning_effort"] = effort
        if tools:
            payload["tools"] = tools
        if stream_options:
            payload["stream_options"] = stream_options
        return payload

    @staticmethod
    def _usage_to_ollama(
        usage: Dict[str, Any],
        *,
        started_at: float,
        first_token_at: Optional[float],
    ) -> Dict[str, Any]:
        """Synthesize the Ollama timing block from usage + wall clock."""
        completion = int(usage.get("completion_tokens") or 0)
        prompt = int(usage.get("prompt_tokens") or 0)
        total_s = max(time.monotonic() - started_at, 1e-9)
        eval_s = max(
            (time.monotonic() - (first_token_at or started_at)) or 0.0, 1e-9
        )
        return {
            "eval_count": completion,
            "prompt_eval_count": prompt,
            "eval_duration": int(eval_s * 1e9),
            "prompt_eval_duration": int((total_s - eval_s) * 1e9),
            "total_duration": int(total_s * 1e9),
        }

    @staticmethod
    def _finish_to_done_reason(finish_reason: Optional[str]) -> str:
        return {
            "stop": "stop",
            "length": "length",
            "tool_calls": "tool_calls",
        }.get(finish_reason or "", "stop")

    # ------------------------------------------------------------- public

    async def list_models(self) -> List[Dict[str, Any]]:
        """List served models, Ollama-shaped, limited to our profiles.

        The router also auto-discovers raw HF cache entries; exposing only
        the profile ids keeps the API surface stable for the frontend.
        """
        resp = await self._client().get(f"{self.base_url}/v1/models")
        resp.raise_for_status()
        data = resp.json().get("data", [])
        known = set(RUNTIME_PROFILES)
        return [
            {
                "name": entry.get("id", ""),
                "model": entry.get("id", ""),
                "size": entry.get("meta", {}).get("size", 0),
            }
            for entry in data
            if entry.get("id") in known
        ]

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        think: Union[bool, str] = False,
        num_ctx: Optional[int] = None,
        num_predict: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Non-streaming chat returning an Ollama-style response dict."""
        started_at = time.monotonic()
        payload = self._build_payload(
            model, messages, tools, temperature, num_predict, options,
            think, stream=False,
        )
        resp = await self._client().post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = dict(choice.get("message") or {})
        out_message: Dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        if message.get("reasoning_content"):
            out_message["thinking"] = message["reasoning_content"]
        if message.get("tool_calls"):
            out_message["tool_calls"] = [
                {
                    "function": {
                        "name": call.get("name")
                        or call.get("function", {}).get("name", ""),
                        "arguments": call.get("arguments")
                        or call.get("function", {}).get("arguments", ""),
                    }
                }
                for call in message["tool_calls"]
            ]
        return {
            "model": data.get("model", model),
            "message": out_message,
            "done": True,
            "done_reason": self._finish_to_done_reason(choice.get("finish_reason")),
            **self._usage_to_ollama(
                data.get("usage") or {},
                started_at=started_at,
                first_token_at=None,
            ),
        }

    async def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        num_predict: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
        think: Optional[Union[bool, str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat as Ollama-shaped chunks from the SSE endpoint."""
        profile = get_model_profile(model)
        if think is None:
            think = profile.think
        payload = self._build_payload(
            model, messages, tools, temperature, num_predict, options,
            think, stream=True, stream_options={"include_usage": True},
        )
        started_at = time.monotonic()
        first_token_at: Optional[float] = None
        try:
            async with self._client().stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                usage: Dict[str, Any] = {}
                finish_reason: Optional[str] = None
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or [{}]
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}

                    out_message: Dict[str, Any] = {}
                    if delta.get("reasoning_content"):
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        out_message["thinking"] = delta["reasoning_content"]
                    if delta.get("content"):
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        out_message["content"] = delta["content"]
                    if delta.get("tool_calls"):
                        out_message["tool_calls"] = delta["tool_calls"]
                    if out_message:
                        yield {"message": out_message}

                yield {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": self._finish_to_done_reason(finish_reason),
                    **self._usage_to_ollama(
                        usage,
                        started_at=started_at,
                        first_token_at=first_token_at,
                    ),
                }
        except (httpx.HTTPError, OSError) as exc:
            yield {
                "_error": type(exc).__name__,
                "done": True,
                "done_reason": "inference_error",
            }
