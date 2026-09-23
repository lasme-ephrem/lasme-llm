import base64
import urllib.parse
import urllib.request
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from core.config import settings

# Folder where generated PNG images will be stored
IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "chat" / "web" / "generated_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def _looks_like_supported_image(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )

def save_base64_image(base64_str: str) -> Optional[str]:
    """Saves a base64 image string to local disk and returns local relative URL."""
    try:
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]
        img_bytes = base64.b64decode(base64_str, validate=True)
        if len(img_bytes) > settings.max_upload_bytes:
            return None
        if not _looks_like_supported_image(img_bytes):
            return None
        filename = f"input_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        filepath = IMAGES_DIR / filename
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        return f"/generated_images/{filename}"
    except Exception as e:
        return None

def generate_image_from_prompt(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    image_input_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a high-resolution photorealistic or anatomical image (FLUX.1 / SDXL engine)
    and saves it to local disk. Safe from HTTP 414 Request-URI Too Large errors.
    """
    try:
        if not settings.external_image_generation_enabled:
            raise RuntimeError(
                "External image generation is disabled by configuration."
            )

        # Save base64 input image if present to prevent HTTP 414 URI Too Large errors
        saved_input_url = None
        if image_input_url:
            if image_input_url.startswith("data:image") or len(image_input_url) > 1000:
                saved_input_url = save_base64_image(image_input_url)
            else:
                saved_input_url = image_input_url

        if saved_input_url and saved_input_url.startswith("/"):
            if not settings.public_base_url:
                raise RuntimeError(
                    "Image editing requires LASME_PUBLIC_BASE_URL so the external "
                    "image provider can access the source image."
                )
            saved_input_url = f"{settings.public_base_url}{saved_input_url}"

        # Generate unique filename
        filename = f"gen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        filepath = IMAGES_DIR / filename
        
        # Clean & sanitize prompt for URL
        encoded_prompt = urllib.parse.quote(prompt.strip())
        
        # Seed adds randomness for unique generations
        seed = int(datetime.datetime.now().timestamp() * 1000) % 10000000
        
        # Pollinations FLUX / SDXL endpoint (clean prompt without heavy query parameters)
        base_endpoint = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"
        
        # Only attach image parameter if it's a short external URL (not a massive base64 string)
        if saved_input_url and not saved_input_url.startswith("data:") and len(saved_input_url) < 500:
            encoded_img = urllib.parse.quote(saved_input_url)
            base_endpoint += f"&image={encoded_img}"
            
        req = urllib.request.Request(
            base_endpoint,
            headers={"User-Agent": "LasmeLLM/1.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        with urllib.request.urlopen(req, timeout=55.0) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                raise RuntimeError(
                    f"Image provider returned unsupported content type: {content_type}"
                )
            image_bytes = response.read(MAX_IMAGE_BYTES + 1)
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise RuntimeError("Generated image exceeds the 15 MB limit.")
            if not _looks_like_supported_image(image_bytes):
                raise RuntimeError("Image provider returned invalid image data.")
            with open(filepath, "wb") as out_file:
                out_file.write(image_bytes)
            
        return {
            "status": "success",
            "filename": filename,
            "image_url": f"/generated_images/{filename}",
            "prompt": prompt,
            "input_image_url": saved_input_url
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "prompt": prompt
        }
