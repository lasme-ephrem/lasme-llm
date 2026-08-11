import json
from typing import AsyncGenerator, Dict, List, Any, Optional, Union
import httpx
from core.config import settings
from core.inference.profiles import get_model_profile

class LasmeLLMClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip('/')
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

    async def list_models(self) -> List[Dict[str, Any]]:
        """List locally available models in Ollama."""
        resp = await self._client().get(
            f"{self.base_url}/api/tags",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])

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
        """Send a chat completion request to local Ollama API with extended token capacity."""
        profile = get_model_profile(model)
        opts = {
            "temperature": (
                profile.temperature if temperature is None else temperature
            ),
            "num_predict": num_predict or profile.num_predict,
            "num_ctx": num_ctx or profile.num_ctx,
            **profile.options,
        }
        if options:
            opts.update(options)

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "think": think,
            "keep_alive": profile.keep_alive,
            "options": opts,
        }
        if tools:
            payload["tools"] = tools

        resp = await self._client().post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()

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
        """Stream chat responses chunk by chunk from Ollama with intelligence-level params."""
        profile = get_model_profile(model)
        opts = {
            "temperature": (
                profile.temperature if temperature is None else temperature
            ),
            "num_predict": num_predict or profile.num_predict,
            "num_ctx": num_ctx or profile.num_ctx,
            **profile.options,
        }
        if options:
            opts.update(options)

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": profile.think if think is None else think,
            "keep_alive": profile.keep_alive,
            "options": opts,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with self._client().stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            yield chunk
                        except json.JSONDecodeError:
                            continue
        except (httpx.HTTPError, OSError) as exc:
            yield {
                "_error": type(exc).__name__,
                "done": True,
                "done_reason": "inference_error",
            }
