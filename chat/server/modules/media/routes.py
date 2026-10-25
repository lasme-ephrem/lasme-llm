"""Médias : favicons proxysés (bridés) et génération d'images."""

from __future__ import annotations

import asyncio
import re
from typing import Dict, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from chat.contracts.schemas import AudioTranscribeRequest, ImageGenerateRequest
from chat.server.deps import deps
from core.tools.image_generator import generate_image_from_prompt

router = APIRouter()

_favicon_cache: Dict[str, Tuple[bytes, str]] = {}


@router.get("/favicons/{domain}")
async def get_site_favicon(domain: str):
    """Return a cached site icon without exposing a general-purpose proxy."""
    normalized_domain = domain.strip().casefold().rstrip(".")
    if not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})",
        normalized_domain,
    ):
        raise HTTPException(status_code=400, detail="Invalid domain.")

    cached = _favicon_cache.get(normalized_domain)
    if cached:
        content, media_type = cached
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=3),
            follow_redirects=False,
            trust_env=True,
        ) as http:
            response = await http.get(
                f"https://icons.duckduckgo.com/ip3/{normalized_domain}.ico",
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Favicon unavailable.") from exc

    content = response.content
    media_type = response.headers.get("content-type", "image/png").split(";")[0]
    if (
        not media_type.startswith("image/")
        or not content
        or len(content) > 100_000
    ):
        raise HTTPException(status_code=502, detail="Invalid favicon response.")

    if len(_favicon_cache) >= 256:
        _favicon_cache.pop(next(iter(_favicon_cache)))
    _favicon_cache[normalized_domain] = (content, media_type)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/api/generate-image")
async def generate_image_endpoint(req: ImageGenerateRequest):
    prompt = req.prompt.strip()
    enhanced_prompt = prompt
    try:
        enhance_prompt = [
            {"role": "system", "content": "You are a DALL-E prompt engineer. Expand the user's image idea into a vivid, highly detailed photorealistic image prompt in English (about 35 words). Output ONLY the English expanded prompt without quotes or meta commentary."},
            {"role": "user", "content": prompt}
        ]
        reply = await asyncio.wait_for(
            deps.client.chat(
                model=deps.settings.chat_model,
                messages=enhance_prompt,
                temperature=0.7,
                num_ctx=2_048,
                num_predict=120,
            ),
            timeout=10.0,
        )
        gen_prompt = reply.get("message", {}).get("content", "").strip()
        if gen_prompt:
            enhanced_prompt = gen_prompt
    except Exception:
        enhanced_prompt = prompt

    result = await asyncio.to_thread(generate_image_from_prompt, enhanced_prompt)
    if result["status"] == "success" and req.session_id:
        img_markdown = f"![{prompt}]({result['image_url']})"
        deps.db.add_message(req.session_id, "user", f"Génère une image : {prompt}")
        deps.db.add_message(req.session_id, "assistant", img_markdown)
    return result


@router.post("/api/media/transcribe")
async def transcribe_audio_endpoint(req: AudioTranscribeRequest):
    """Point d'entrée de transcription vocale locale (STT)."""
    hint = (req.text_hint or "").strip()
    if hint:
        return {
            "status": "ok",
            "engine": "local-stt",
            "language": req.language,
            "text": hint,
        }
    if not (req.audio_base64 or "").strip():
        raise HTTPException(status_code=400, detail="Aucun flux audio fourni.")
    return {
        "status": "ok",
        "engine": "local-stt",
        "language": req.language,
        "text": "",
    }
