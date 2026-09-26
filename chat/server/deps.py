"""Dépendances applicatives — injection remplaçant les singletons de main.py.

``deps.client`` utilise une **liaison tardive** sur
``chat.server.main.client`` : cela préserve la couture de test historique
``patch("chat.server.main.client", ...)`` utilisée par la suite de tests,
tout en laissant les modules indépendants du monolithe.
"""

from __future__ import annotations

from typing import Any, Dict

from core.config import settings as app_settings


class Deps:
    """Conteneur mutable des services partagés (composition root).

    Chaque accès résout d'abord l'attribut de même nom dans
    ``chat.server.main`` : c'est la couture de tests historique
    (``patch("chat.server.main.rag_store", ...)`` et consorts) qui doit
    rester visible, comme dans l'ancien monolithe.
    """

    def __init__(self) -> None:
        self.settings: Any = app_settings
        self._stores: Dict[str, Any] = {}

    def bind_client(self, client: Any) -> Any:
        """Enregistre le client d'inférence et le retourne (pour main.py)."""
        self._stores["client"] = client
        return client

    def bind(self, **stores: Any) -> "Deps":
        """Force les valeurs (les tests remplacent ici un store)."""
        self._stores.update(stores)
        return self

    def bind_missing(self, **stores: Any) -> "Deps":
        """Complète SANS écraser : l'import tardif de main (via _resolve)
        ne doit jamais rebinder un store déjà fourni (cas des tests)."""
        for name, value in stores.items():
            self._stores.setdefault(name, value)
        return self

    @property
    def job_store(self) -> Any:
        return self._resolve("job_store")

    def _resolve(self, name: str) -> Any:
        try:
            import chat.server.main as main_module

            bound = getattr(main_module, name, None)
            if bound is not None:
                return bound
        except Exception:
            pass
        return self._stores.get(name)

    @property
    def client(self) -> Any:
        return self._resolve("client")

    @property
    def db(self) -> Any:
        return self._resolve("db")

    @property
    def rag_store(self) -> Any:
        return self._resolve("rag_store")

    @property
    def project_file_store(self) -> Any:
        return self._resolve("project_file_store")

    @property
    def artifact_store(self) -> Any:
        return self._resolve("artifact_store")

    @property
    def python_runner(self) -> Any:
        return self._resolve("python_runner")


deps = Deps()


def build_deps() -> Deps:
    """Câble les stores partagés (SQLite, RAG, fichiers, artefacts, runner)."""
    from core.artifacts import artifact_store
    from core.files import project_file_store
    from core.memory.database import db as database
    from core.memory.jobs import JobStore
    from core.rag.store import rag_store
    from core.runner import python_runner

    return deps.bind_missing(
        db=database,
        rag_store=rag_store,
        project_file_store=project_file_store,
        artifact_store=artifact_store,
        python_runner=python_runner,
        job_store=JobStore(database.db_path),
    )
