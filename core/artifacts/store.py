from __future__ import annotations

import datetime
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.memory.database import DB_PATH, DEFAULT_PROJECT_ID


ARTIFACT_KINDS = {
    "document",
    "code",
    "markdown",
    "table",
    "research",
    "html",
    "interactive",
    "diagram",
    "mindmap",
    "chart",
    "presentation",
}


class ArtifactStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    session_id TEXT,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_project
                    ON artifacts(project_id, updated_at);

                CREATE TABLE IF NOT EXISTS artifact_versions (
                    id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    source_message_id TEXT,
                    change_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (artifact_id)
                        REFERENCES artifacts(id) ON DELETE CASCADE,
                    UNIQUE(artifact_id, version_number)
                );
                CREATE INDEX IF NOT EXISTS idx_artifact_versions
                    ON artifact_versions(artifact_id, version_number DESC);
                """
            )

    def list(self, project_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a.*,
                       COALESCE(MAX(v.version_number), 0) AS version_count
                FROM artifacts a
                LEFT JOIN artifact_versions v ON v.artifact_id = a.id
                WHERE a.project_id = ?
                GROUP BY a.id
                ORDER BY a.updated_at DESC
                """,
                ((project_id or DEFAULT_PROJECT_ID).strip(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if not artifact:
                return None
            versions = conn.execute(
                """
                SELECT id, version_number, content, source_message_id,
                       change_summary, created_at
                FROM artifact_versions
                WHERE artifact_id = ?
                ORDER BY version_number DESC
                """,
                (artifact_id,),
            ).fetchall()
        result = dict(artifact)
        result["versions"] = [dict(row) for row in versions]
        result["content"] = versions[0]["content"] if versions else ""
        result["current_version"] = (
            int(versions[0]["version_number"]) if versions else 0
        )
        return result

    def create(
        self,
        *,
        project_id: str,
        title: str,
        content: str,
        kind: str = "document",
        language: str = "",
        session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_kind = kind if kind in ARTIFACT_KINDS else "document"
        artifact_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts
                    (id, project_id, session_id, title, kind, language,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    project_id or DEFAULT_PROJECT_ID,
                    session_id,
                    title.strip()[:160] or "Sans titre",
                    normalized_kind,
                    language.strip()[:40],
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO artifact_versions
                    (id, artifact_id, version_number, content,
                     source_message_id, change_summary, created_at)
                VALUES (?, ?, 1, ?, ?, 'Création', ?)
                """,
                (
                    str(uuid.uuid4()),
                    artifact_id,
                    content,
                    source_message_id,
                    now,
                ),
            )
        return self.get(artifact_id) or {}

    def add_version(
        self,
        artifact_id: str,
        content: str,
        *,
        title: Optional[str] = None,
        change_summary: str = "",
        kind: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) AS version_number
                FROM artifact_versions WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
            if not conn.execute(
                "SELECT 1 FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone():
                return None
            next_version = int(row["version_number"]) + 1
            conn.execute(
                """
                INSERT INTO artifact_versions
                    (id, artifact_id, version_number, content,
                     change_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    artifact_id,
                    next_version,
                    content,
                    change_summary.strip()[:240],
                    now,
                ),
            )
            updates = ["updated_at = ?"]
            values: List[Any] = [now]
            if title is not None:
                updates.append("title = ?")
                values.append(title.strip()[:160] or "Sans titre")
            if kind is not None:
                updates.append("kind = ?")
                values.append(kind if kind in ARTIFACT_KINDS else "document")
            values.append(artifact_id)
            conn.execute(
                f"UPDATE artifacts SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        return self.get(artifact_id)

    def delete(self, artifact_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM artifacts WHERE id = ?",
                (artifact_id,),
            )
            return cursor.rowcount > 0

    def clear_project(self, project_id: str) -> int:
        scope = (project_id or DEFAULT_PROJECT_ID).strip()
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM artifacts WHERE project_id = ?",
                (scope,),
            )
            return max(0, int(cursor.rowcount))


artifact_store = ArtifactStore()
