"""File de jobs durable (SQLite) — titrage, compaction, mémoire, indexation.

Remplace les ``asyncio.create_task`` nus des routes : un job est persisté
avant exécution, rejouable, observable, et survit à un redémarrage.
Les ``-wal`` ne sont jamais supprimés (voir docs/ADR-001-stockage-donnees.md).
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

# Kinds de jobs pris en charge par chat.worker.loop.
JOB_KINDS = {
    "title",
    "session_memory",
    "personal_memory",
    "document_index",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class _ClosingConnection:
    """Connection SQLite qui se FERME à la sortie du `with`.

    Le context manager natif de sqlite3 ne fait que commit/rollback : sur
    Windows laissé ouvert, le fichier reste verrouillé (WinError 32).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()

    def __getattr__(self, item):
        return getattr(self._conn, item)


class JobStore:
    """Petite file persistante adossée à la base applicative."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> _ClosingConnection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA wal_autocheckpoint = 64;")
        conn.row_factory = sqlite3.Row
        return _ClosingConnection(conn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def enqueue(self, kind: str, payload: Optional[Dict[str, Any]] = None) -> str:
        if kind not in JOB_KINDS:
            raise ValueError(f"Unknown job kind: {kind}")
        job_id = uuid.uuid4().hex
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, payload, status, attempts, error,"
                " created_at, updated_at) VALUES (?, ?, ?, 'pending', 0, '', ?, ?)",
                (job_id, kind, json.dumps(payload or {}, ensure_ascii=False), now, now),
            )
        return job_id

    def claim_next(self) -> Optional[Dict[str, Any]]:
        """Réserve le plus vieux job pending (marqué running, atomique)."""
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending'"
                " ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if not row:
                return None
            updated = conn.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1,"
                " updated_at = ? WHERE id = ? AND status = 'pending'",
                (now, row["id"]),
            )
            if updated.rowcount != 1:
                return None
        job = dict(row)
        job["payload"] = json.loads(job.get("payload") or "{}")
        return job

    def complete(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done', error = '', updated_at = ?"
                " WHERE id = ?",
                (self._now(), job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'error', error = ?, updated_at = ?"
                " WHERE id = ?",
                (str(error)[:500], self._now(), job_id),
            )

    def pending_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('pending', 'running')"
            ).fetchone()
            return int(row["n"] if row else 0)

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        jobs = [dict(row) for row in rows]
        for job in jobs:
            try:
                job["payload"] = json.loads(job.get("payload") or "{}")
            except Exception:
                job["payload"] = {}
        return jobs

    def requeue_stale_running(self, older_than_seconds: int = 600) -> int:
        """Remet en pending les jobs running orphelins (crash du worker)."""
        cutoff = self._now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, updated_at FROM jobs WHERE status = 'running'"
            ).fetchall()
            stale = []
            for row in rows:
                try:
                    updated = datetime.datetime.fromisoformat(row["updated_at"])
                    age = (
                        datetime.datetime.now(datetime.timezone.utc) - updated
                    ).total_seconds()
                    if age > older_than_seconds:
                        stale.append(row["id"])
                except Exception:
                    continue
            for job_id in stale:
                conn.execute(
                    "UPDATE jobs SET status = 'pending', updated_at = ?"
                    " WHERE id = ?",
                    (cutoff, job_id),
                )
            return len(stale)
