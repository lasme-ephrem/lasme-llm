"""Model inventory, VRAM detection and downloads for the v2 runtime."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from core.config import settings
from core.inference.profiles import RuntimeProfile


@dataclass(frozen=True)
class CachedModel:
    repo_id: str          # e.g. unsloth/gemma-4-12B-it-qat-GGUF
    snapshot_dir: Path
    gguf_files: Dict[str, int]  # filename -> size bytes
    has_mmproj: bool
    has_mtp_drafter: bool

    @property
    def total_bytes(self) -> int:
        return sum(self.gguf_files.values())


def default_hf_cache() -> Path:
    if settings.hf_cache_dir:
        return Path(settings.hf_cache_dir)
    return Path.home() / ".cache" / "huggingface"


def detect_vram_mib() -> Optional[int]:
    """Total VRAM of the primary GPU, MiB, or None when unavailable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first = result.stdout.strip().splitlines()[0]
        return int(first)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


_REPO_DIR_RE = re.compile(r"^models--(.+)--(.+)$")


def scan_hf_cache(cache_root: Optional[Path] = None) -> List[CachedModel]:
    """List GGUF models available in the local HuggingFace cache."""
    root = cache_root or default_hf_cache() / "hub"
    models: List[CachedModel] = []
    if not root.is_dir():
        return models
    for entry in sorted(root.iterdir()):
        match = _REPO_DIR_RE.match(entry.name)
        if not match or not entry.is_dir():
            continue
        repo_id = f"{match.group(1)}/{match.group(2)}"
        snapshots = entry / "snapshots"
        if not snapshots.is_dir():
            continue
        for snapshot in sorted(snapshots.iterdir()):
            if not snapshot.is_dir():
                continue
            files: Dict[str, int] = {}
            for gguf in snapshot.glob("*.gguf"):
                try:
                    files[gguf.name] = gguf.stat().st_size
                except OSError:
                    continue
            if not files:
                continue
            names = " ".join(files).lower()
            models.append(
                CachedModel(
                    repo_id=repo_id,
                    snapshot_dir=snapshot,
                    gguf_files=files,
                    has_mmproj=any(n.startswith("mmproj") for n in files)
                    or "mmproj" in names,
                    has_mtp_drafter="mtp" in names,
                )
            )
            break  # newest snapshot listing is enough
    return models


def is_profile_downloaded(profile: RuntimeProfile, cache_root: Optional[Path] = None) -> bool:
    """True when the profile's base GGUF exists in the HF cache."""
    repo = profile.hf_repo.split(":")[0].lower()
    for model in scan_hf_cache(cache_root):
        if model.repo_id.lower() != repo:
            continue
        base = [n for n in model.gguf_files if not n.startswith("mmproj") and "mtp" not in n.lower()]
        return bool(base)
    return False
