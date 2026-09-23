"""CLI de pilotage du runtime llama.cpp v2.

Usage :
  python -m scripts.serve status
  python -m scripts.serve start
  python -m scripts.serve stop
  python -m scripts.serve metrics --model gemma-4-e4b
  python -m scripts.serve info
"""

from __future__ import annotations

import asyncio
import json

import typer

from core.config import settings
from core.inference import manager
from core.inference.profiles import RUNTIME_PROFILES
from core.inference.supervisor import LlamaServerSupervisor, resolve_server_executable

app = typer.Typer(add_completion=False, help="Superviseur llama-server Lasme v2")


def _supervisor() -> LlamaServerSupervisor:
    return LlamaServerSupervisor(vram_total_mib=manager.detect_vram_mib())


@app.command()
def start() -> None:
    """Démarre le router llama-server (idempotent)."""
    supervisor = _supervisor()
    try:
        status = asyncio.run(supervisor.start())
    except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(
        f"llama-server sain sur {status.base_url} "
        f"(exe: {status.executable}, preset: {status.preset_path})",
        fg=typer.colors.GREEN,
    )


@app.command()
def stop() -> None:
    """Arrête le router et ses instances filles."""
    supervisor = _supervisor()
    stopped = asyncio.run(supervisor.stop())
    typer.secho(
        "llama-server arrêté." if stopped else "Aucun processus à arrêter.",
        fg=typer.colors.GREEN if stopped else typer.colors.YELLOW,
    )


@app.command()
def status() -> None:
    """État du runtime."""
    status = asyncio.run(_supervisor().status())
    typer.echo(json.dumps(status.__dict__, indent=2, ensure_ascii=False, default=str))


@app.command()
def metrics(model: str = typer.Option(..., help="ID du profil, ex: gemma-4-e4b")) -> None:
    """Métriques Prometheus d'un modèle routé."""
    values = asyncio.run(_supervisor().metrics(model))
    typer.echo(json.dumps(values, indent=2))


@app.command()
def info() -> None:
    """Inventaire : GPU, exécutable, modèles en cache, profils."""
    executable = resolve_server_executable(settings.llama_server_path)
    vram = manager.detect_vram_mib()
    cached = manager.scan_hf_cache()
    typer.echo(f"llama-server : {executable or 'INTROUVABLE'}")
    typer.echo(f"VRAM totale  : {vram} MiB" if vram else "VRAM totale  : non détectée")
    typer.echo(f"base_url     : {settings.llama_base_url}")
    typer.echo("\nProfils :")
    for profile in RUNTIME_PROFILES.values():
        downloaded = manager.is_profile_downloaded(profile)
        typer.echo(
            f"  [{'x' if downloaded else ' '}] {profile.id:<20} "
            f"ctx={profile.context:<7} kv={profile.kv_quant:<5} "
            f"{'resident' if profile.resident else 'à la demande':<13} "
            f"— {profile.description}"
        )
    typer.echo("\nCache HF :")
    if not cached:
        typer.echo("  (vide)")
    for model in cached:
        typer.echo(
            f"  {model.repo_id} — {model.total_bytes / 1e9:.2f} Go, "
            f"{len(model.gguf_files)} gguf, "
            f"{'vision+' if model.has_mmproj else ''}"
            f"{'MTP' if model.has_mtp_drafter else ''}"
        )


if __name__ == "__main__":
    app()
