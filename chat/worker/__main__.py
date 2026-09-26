"""Worker de jobs en process séparé : ``python -m chat.worker``.

Usage (phase F / déploiement multi-process) : le lifespan de l'API tourne
déjà le même loop en interne — n'utiliser ce binaire que pour sortir le
worker du process API. Arrêt propre : SIGINT/SIGTERM → checkpoint WAL.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from chat.server.deps import build_deps
from chat.worker.loop import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lasme.worker")


async def main() -> None:
    deps = build_deps()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    task = asyncio.create_task(worker_loop())
    await stop.wait()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    try:
        deps.db.checkpoint()  # arrêt propre : journal WAL rapatrié
    except Exception:
        pass
    logger.info("worker arrêté proprement")


if __name__ == "__main__":
    asyncio.run(main())
