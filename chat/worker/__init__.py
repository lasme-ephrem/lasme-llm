"""Worker de jobs de fond (phases D2/E).

Le même loop tourne :
- **en process** : lancé par le lifespan de ``chat.server.app`` (mode par
  défaut, aucun changement d'exploitation) ;
- **en process séparé** : ``python -m chat.worker`` (extraction future,
  phase F).

La réservation de job est atomique : deux workers ne traitent jamais le
même job.
"""

from chat.worker.loop import process_one, worker_loop  # noqa: F401
