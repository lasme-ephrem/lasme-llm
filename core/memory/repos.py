"""Repositories par domaine (phase D1) — façades sur ``DatabaseManager``.

``DatabaseManager`` implémente déjà l'accès SQL par domaine (sessions,
projets, mémoires, runs agent) : ces façades nomment explicitement le
contrat de chaque domaine et servent de couture de remplacement si le
stockage change (cf. docs/ADR-001-stockage-donnees.md).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class SessionRepo:
    """Fil de conversation : sessions et messages."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def list(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._db.list_sessions(project_id)

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._db.get_session(session_id)

    def messages(self, session_id: str) -> List[Dict[str, Any]]:
        return self._db.get_session_messages(session_id)

    def add_message(self, session_id: str, role: str, content: str, **kwargs):
        return self._db.add_message(session_id, role, content, **kwargs)


class ProjectRepo:
    """Espaces de travail."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def list(self) -> List[Dict[str, Any]]:
        return self._db.list_projects()

    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._db.get_project(project_id)


class MemoryRepo:
    """Mémoire personnelle et réglages."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def settings(self) -> Dict[str, Any]:
        return self._db.get_memory_settings()

    def list(self, include_disabled: bool = True) -> List[Dict[str, Any]]:
        return self._db.list_personal_memories(include_disabled=include_disabled)


class AgentRunRepo:
    """Journal des runs agent (replay, sources, usage)."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def save(self, **kwargs) -> str:
        return self._db.save_agent_run(**kwargs)

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._db.get_agent_run(run_id)


def build_repos(db: Any) -> Dict[str, Any]:
    """Fabrique toutes les façades à partir d'une base partagée."""
    return {
        "sessions": SessionRepo(db),
        "projects": ProjectRepo(db),
        "memory": MemoryRepo(db),
        "agent_runs": AgentRunRepo(db),
    }
