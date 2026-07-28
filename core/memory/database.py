import sqlite3
import uuid
import datetime
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "lasme_llm.db"
SCHEMA_VERSION = 2
DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Espace principal"
DEFAULT_PROJECT_DESCRIPTION = "Espace permanent pour vos conversations générales."
PROJECT_TYPES = {
    "general",
    "research",
    "learning",
    "data",
    "coding",
    "writing",
    "media",
}
PROJECT_COLORS = {
    "general": "#5B6EE1",
    "research": "#7C5CE7",
    "learning": "#D97706",
    "data": "#2563EB",
    "coding": "#0F766E",
    "writing": "#DB2777",
    "media": "#EA580C",
}

class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._backup_before_migration()
        self._init_db()

    def _backup_before_migration(self) -> None:
        if self.db_path != DB_PATH or not self.db_path.is_file():
            return
        try:
            with sqlite3.connect(self.db_path) as source:
                current_version = int(
                    source.execute("PRAGMA user_version").fetchone()[0]
                )
                if current_version >= SCHEMA_VERSION:
                    return
                backup_root = (
                    self.db_path.parent / ".runtime" / "db_backups"
                )
                backup_root.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.datetime.now().strftime(
                    "%Y%m%d-%H%M%S-%f"
                )
                backup_path = backup_root / (
                    f"{self.db_path.stem}-v{current_version}-{timestamp}.db"
                )
                with sqlite3.connect(backup_path) as destination:
                    source.backup(destination)
        except sqlite3.Error:
            # A backup failure must not silently mutate an unknown schema.
            raise RuntimeError(
                "Unable to create the pre-migration database backup."
            )

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._get_connection()
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    summary_message_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personal_memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    instructions TEXT NOT NULL DEFAULT '',
                    default_model TEXT NOT NULL DEFAULT 'gemma-4-chat',
                    memory_mode TEXT NOT NULL DEFAULT 'project',
                    project_type TEXT NOT NULL DEFAULT 'general',
                    tags TEXT NOT NULL DEFAULT '[]',
                    color TEXT NOT NULL DEFAULT '#5B6EE1',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            now = datetime.datetime.now().isoformat()
            cursor.execute(
                """
                INSERT OR IGNORE INTO projects
                    (id, name, description, instructions, default_model,
                     memory_mode, created_at, updated_at)
                VALUES (?, ?, ?, '', 'gemma-4-chat', 'global', ?, ?)
                """,
                (
                    DEFAULT_PROJECT_ID,
                    DEFAULT_PROJECT_NAME,
                    DEFAULT_PROJECT_DESCRIPTION,
                    now,
                    now,
                ),
            )
            project_columns = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(projects)").fetchall()
            }
            project_migrations = {
                "project_type": (
                    "ALTER TABLE projects ADD COLUMN "
                    "project_type TEXT NOT NULL DEFAULT 'general'"
                ),
                "tags": (
                    "ALTER TABLE projects ADD COLUMN "
                    "tags TEXT NOT NULL DEFAULT '[]'"
                ),
                "color": (
                    "ALTER TABLE projects ADD COLUMN "
                    "color TEXT NOT NULL DEFAULT '#5B6EE1'"
                ),
                "favorite": (
                    "ALTER TABLE projects ADD COLUMN "
                    "favorite INTEGER NOT NULL DEFAULT 0"
                ),
            }
            for column, statement in project_migrations.items():
                if column not in project_columns:
                    cursor.execute(statement)
            cursor.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, instructions = '',
                    project_type = 'general', color = '#5B6EE1'
                WHERE id = ?
                """,
                (
                    DEFAULT_PROJECT_NAME,
                    DEFAULT_PROJECT_DESCRIPTION,
                    DEFAULT_PROJECT_ID,
                ),
            )
            cursor.execute(
                "UPDATE projects SET default_model = 'gemma-4-chat' "
                "WHERE default_model = 'gemma-4-fable'"
            )
            session_columns = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "summary" not in session_columns:
                cursor.execute(
                    "ALTER TABLE sessions ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
                )
            if "summary_message_count" not in session_columns:
                cursor.execute(
                    "ALTER TABLE sessions ADD COLUMN "
                    "summary_message_count INTEGER NOT NULL DEFAULT 0"
                )
            if "project_id" not in session_columns:
                cursor.execute(
                    "ALTER TABLE sessions ADD COLUMN project_id TEXT "
                    f"NOT NULL DEFAULT '{DEFAULT_PROJECT_ID}'"
                )
            if "parent_session_id" not in session_columns:
                cursor.execute(
                    "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT"
                )
            if "branch_from_message_id" not in session_columns:
                cursor.execute(
                    "ALTER TABLE sessions ADD COLUMN branch_from_message_id TEXT"
                )
            cursor.execute(
                "UPDATE sessions SET model = 'gemma-4-chat' "
                "WHERE model = 'gemma-4-fable'"
            )
            message_columns = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "metadata" not in message_columns:
                cursor.execute(
                    "ALTER TABLE messages ADD COLUMN "
                    "metadata TEXT NOT NULL DEFAULT '{}'"
                )
            if "edited_at" not in message_columns:
                cursor.execute("ALTER TABLE messages ADD COLUMN edited_at TIMESTAMP")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_project "
                "ON sessions(project_id, updated_at)"
            )
            cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        now = datetime.datetime.now().isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value), now),
            )
            conn.commit()

    def get_memory_settings(self) -> Dict[str, Any]:
        return {
            "enabled": self.get_setting("memory_enabled", "true") == "true",
            "auto_save": self.get_setting("memory_auto_save", "true") == "true",
            "prompt_counter": int(
                self.get_setting("memory_prompt_counter", "0") or 0
            ),
        }

    def update_memory_settings(
        self,
        *,
        enabled: Optional[bool] = None,
        auto_save: Optional[bool] = None,
        prompt_counter: Optional[int] = None,
    ) -> Dict[str, Any]:
        if enabled is not None:
            self.set_setting("memory_enabled", "true" if enabled else "false")
        if auto_save is not None:
            self.set_setting(
                "memory_auto_save",
                "true" if auto_save else "false",
            )
        if prompt_counter is not None:
            self.set_setting(
                "memory_prompt_counter",
                str(max(0, int(prompt_counter))),
            )
        return self.get_memory_settings()

    def list_personal_memories(
        self,
        include_disabled: bool = True,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT id, content, source, enabled, created_at, updated_at
            FROM personal_memories
        """
        params: tuple[Any, ...] = ()
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY updated_at DESC"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                **dict(row),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def add_personal_memory(
        self,
        content: str,
        source: str = "user",
        enabled: bool = True,
    ) -> Dict[str, Any]:
        normalized = " ".join((content or "").split()).strip()
        if not normalized:
            raise ValueError("Memory content cannot be empty.")
        if len(normalized) > 300:
            raise ValueError("Memory content exceeds 300 characters.")
        duplicate_key = normalized.casefold()
        for item in self.list_personal_memories():
            if str(item["content"]).casefold() == duplicate_key:
                return item

        memory_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO personal_memories
                    (id, content, source, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    normalized,
                    source if source in {"user", "generated"} else "user",
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "id": memory_id,
            "content": normalized,
            "source": source,
            "enabled": enabled,
            "created_at": now,
            "updated_at": now,
        }

    def update_personal_memory(
        self,
        memory_id: str,
        *,
        content: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        updates: List[str] = []
        values: List[Any] = []
        if content is not None:
            normalized = " ".join(content.split()).strip()
            if not normalized:
                raise ValueError("Memory content cannot be empty.")
            if len(normalized) > 300:
                raise ValueError("Memory content exceeds 300 characters.")
            updates.extend(["content = ?", "source = 'user'"])
            values.append(normalized)
        if enabled is not None:
            updates.append("enabled = ?")
            values.append(1 if enabled else 0)
        if not updates:
            return next(
                (
                    item
                    for item in self.list_personal_memories()
                    if item["id"] == memory_id
                ),
                None,
            )
        updates.append("updated_at = ?")
        values.append(datetime.datetime.now().isoformat())
        values.append(memory_id)
        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE personal_memories SET {', '.join(updates)} WHERE id = ?",
                tuple(values),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return next(
            (
                item
                for item in self.list_personal_memories()
                if item["id"] == memory_id
            ),
            None,
        )

    def delete_personal_memory(self, memory_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM personal_memories WHERE id = ?",
                (memory_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def replace_generated_memories(self, contents: List[str]) -> None:
        now = datetime.datetime.now().isoformat()
        cleaned: List[str] = []
        seen: set[str] = set()
        for content in contents:
            normalized = " ".join(str(content).split()).strip()[:300]
            key = normalized.casefold()
            if len(normalized) < 8 or key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)

        with self._connection() as conn:
            conn.execute(
                "DELETE FROM personal_memories WHERE source = 'generated'"
            )
            conn.executemany(
                """
                INSERT INTO personal_memories
                    (id, content, source, enabled, created_at, updated_at)
                VALUES (?, ?, 'generated', 1, ?, ?)
                """,
                [
                    (str(uuid.uuid4()), content, now, now)
                    for content in cleaned
                ],
            )
            conn.commit()

    def list_recent_user_prompts(self, limit: int = 100) -> List[str]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT content
                FROM messages
                WHERE role = 'user'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        prompts: List[str] = []
        seen: set[str] = set()
        for row in rows:
            content = " ".join(str(row["content"]).split()).strip()[:600]
            key = content.casefold()
            if len(content) < 24 or key in seen:
                continue
            seen.add(key)
            prompts.append(content)
        return prompts

    @staticmethod
    def _serialize_project(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        project = dict(row)
        try:
            tags = json.loads(project.get("tags") or "[]")
        except (TypeError, ValueError):
            tags = []
        project["tags"] = [
            str(tag).strip()[:32]
            for tag in tags
            if str(tag).strip()
        ][:12]
        project["favorite"] = bool(project.get("favorite"))
        project_type = str(project.get("project_type") or "general")
        project["project_type"] = (
            project_type if project_type in PROJECT_TYPES else "general"
        )
        project["color"] = (
            str(project.get("color") or "").strip()
            or PROJECT_COLORS[project["project_type"]]
        )
        return project

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       COUNT(DISTINCT s.id) AS session_count
                FROM projects p
                LEFT JOIN sessions s ON s.project_id = p.id
                GROUP BY p.id
                ORDER BY CASE WHEN p.id = ? THEN 0 ELSE 1 END,
                         p.favorite DESC, p.project_type, p.updated_at DESC
                """,
                (DEFAULT_PROJECT_ID,),
            ).fetchall()
        return [self._serialize_project(row) for row in rows]

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                ((project_id or DEFAULT_PROJECT_ID).strip(),),
            ).fetchone()
        return self._serialize_project(row) if row else None

    def create_project(
        self,
        name: str,
        *,
        description: str = "",
        instructions: str = "",
        default_model: str = "gemma-4-chat",
        memory_mode: str = "project",
        project_type: str = "general",
        tags: Optional[List[str]] = None,
        color: str = "",
        favorite: bool = False,
    ) -> Dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        normalized_type = (
            project_type if project_type in PROJECT_TYPES else "general"
        )
        normalized_tags = [
            str(tag).strip()[:32]
            for tag in (tags or [])
            if str(tag).strip()
        ][:12]
        normalized_color = (
            color.strip() if color.strip().startswith("#")
            else PROJECT_COLORS[normalized_type]
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO projects
                    (id, name, description, instructions, default_model,
                     memory_mode, project_type, tags, color, favorite,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name.strip(),
                    description.strip(),
                    instructions.strip(),
                    default_model,
                    memory_mode,
                    normalized_type,
                    json.dumps(
                        normalized_tags,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    normalized_color,
                    1 if favorite else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_project(project_id) or {}

    def update_project(
        self,
        project_id: str,
        **changes: Any,
    ) -> Optional[Dict[str, Any]]:
        allowed = (
            {"memory_mode"}
            if project_id == DEFAULT_PROJECT_ID
            else {
                "name",
                "description",
                "instructions",
                "default_model",
                "memory_mode",
                "project_type",
                "tags",
                "color",
                "favorite",
            }
        )
        updates: List[str] = []
        values: List[Any] = []
        for key, value in changes.items():
            if key in allowed and value is not None:
                if key == "project_type":
                    value = value if value in PROJECT_TYPES else "general"
                elif key == "tags":
                    value = json.dumps(
                        [
                            str(tag).strip()[:32]
                            for tag in (value or [])
                            if str(tag).strip()
                        ][:12],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                elif key == "favorite":
                    value = 1 if bool(value) else 0
                elif key == "color":
                    candidate = str(value).strip()
                    if not re.fullmatch(r"#[0-9a-fA-F]{6}", candidate):
                        continue
                    value = candidate
                updates.append(f"{key} = ?")
                values.append(
                    value if key in {"favorite", "tags"} else str(value).strip()
                )
        if not updates:
            return self.get_project(project_id)
        updates.append("updated_at = ?")
        values.extend([datetime.datetime.now().isoformat(), project_id])
        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
                tuple(values),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        if project_id == DEFAULT_PROJECT_ID:
            return False
        with self._connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone():
                return False
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            try:
                conn.execute("BEGIN IMMEDIATE")
                if "artifact_versions" in tables and "artifacts" in tables:
                    conn.execute(
                        "DELETE FROM artifact_versions "
                        "WHERE artifact_id IN ("
                        "SELECT id FROM artifacts WHERE project_id = ?"
                        ")",
                        (project_id,),
                    )
                if "artifacts" in tables:
                    conn.execute(
                        "DELETE FROM artifacts WHERE project_id = ?",
                        (project_id,),
                    )
                if "rag_chunks" in tables and "rag_documents" in tables:
                    conn.execute(
                        "DELETE FROM rag_chunks "
                        "WHERE document_id IN ("
                        "SELECT id FROM rag_documents WHERE scope_id = ?"
                        ")",
                        (project_id,),
                    )
                if "rag_documents" in tables:
                    conn.execute(
                        "DELETE FROM rag_documents WHERE scope_id = ?",
                        (project_id,),
                    )
                if "project_files" in tables:
                    conn.execute(
                        "DELETE FROM project_files WHERE project_id = ?",
                        (project_id,),
                    )
                conn.execute(
                    "DELETE FROM sessions WHERE project_id = ?",
                    (project_id,),
                )
                cursor = conn.execute(
                    "DELETE FROM projects WHERE id = ?",
                    (project_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception:
                conn.rollback()
                raise

    def create_session(
        self,
        title: str = "Nouvelle Conversation",
        model: str = "gemma-4-chat",
        project_id: str = DEFAULT_PROJECT_ID,
        parent_session_id: Optional[str] = None,
        branch_from_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        project = self.get_project(project_id) or self.get_project(DEFAULT_PROJECT_ID)
        resolved_project_id = str(project["id"]) if project else DEFAULT_PROJECT_ID
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions
                    (id, title, model, project_id, parent_session_id,
                     branch_from_message_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    model,
                    resolved_project_id,
                    parent_session_id,
                    branch_from_message_id,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "id": session_id,
            "title": title,
            "model": model,
            "project_id": resolved_project_id,
            "parent_session_id": parent_session_id,
            "branch_from_message_id": branch_from_message_id,
            "created_at": now,
        }

    def list_sessions(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            if project_id:
                cursor.execute(
                    "SELECT * FROM sessions WHERE project_id = ? "
                    "ORDER BY updated_at DESC",
                    (project_id,),
                )
            else:
                cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, session_id, role, content, metadata, timestamp, edited_at
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                except (TypeError, ValueError):
                    item["metadata"] = {}
                messages.append(item)
            return messages

    def get_session_memory(self, session_id: str) -> Dict[str, Any]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT summary, summary_message_count FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {"summary": "", "summary_message_count": 0}
            return dict(row)

    def update_session_memory(
        self,
        session_id: str,
        summary: str,
        summary_message_count: int,
    ):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sessions
                SET summary = ?, summary_message_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    summary,
                    max(0, summary_message_count),
                    datetime.datetime.now().isoformat(),
                    session_id,
                ),
            )
            conn.commit()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        msg_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        serialized_metadata = json.dumps(
            metadata or {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connection() as conn:
            cursor = conn.cursor()
            # Ensure session exists to prevent foreign key failure
            cursor.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO sessions
                        (id, title, model, project_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        "Nouvelle Conversation",
                        "gemma-4-chat",
                        DEFAULT_PROJECT_ID,
                        now,
                        now,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO messages
                    (id, session_id, role, content, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    session_id,
                    role,
                    content,
                    serialized_metadata,
                    now,
                ),
            )
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()
        return msg_id

    def update_message(self, message_id: str, content: str) -> Optional[Dict[str, Any]]:
        normalized = (content or "").strip()
        if not normalized:
            raise ValueError("Message content cannot be empty.")
        now = datetime.datetime.now().isoformat()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE messages SET content = ?, edited_at = ? WHERE id = ?",
                (normalized, now, message_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                """
                SELECT id, session_id, role, content, metadata, timestamp, edited_at
                FROM messages WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def branch_session(
        self,
        session_id: str,
        message_id: str,
        *,
        replacement_content: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = self.get_session(session_id)
        if not source:
            raise ValueError("Session not found.")
        messages = self.get_session_messages(session_id)
        target_index = next(
            (index for index, item in enumerate(messages) if item["id"] == message_id),
            None,
        )
        if target_index is None:
            raise ValueError("Message not found in session.")
        title = f"{source['title']} · branche"
        branch = self.create_session(
            title=title[:120],
            model=model or source["model"],
            project_id=source.get("project_id") or DEFAULT_PROJECT_ID,
            parent_session_id=session_id,
            branch_from_message_id=message_id,
        )
        copied = messages[: target_index + 1]
        for index, item in enumerate(copied):
            content = item["content"]
            if index == target_index and replacement_content is not None:
                content = replacement_content.strip()
            self.add_message(
                branch["id"],
                item["role"],
                content,
                metadata=item.get("metadata") or {},
            )
        return branch

    def update_session_title(self, session_id: str, title: str):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
            conn.commit()

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        project_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        updates: List[str] = []
        values: List[Any] = []
        if title is not None:
            updates.append("title = ?")
            values.append(title.strip()[:120] or "Nouvelle Conversation")
        if project_id is not None:
            if not self.get_project(project_id):
                raise ValueError("Project not found.")
            updates.append("project_id = ?")
            values.append(project_id)
        if model is not None:
            updates.append("model = ?")
            values.append(model)
        if updates:
            updates.append("updated_at = ?")
            values.extend([datetime.datetime.now().isoformat(), session_id])
            with self._connection() as conn:
                cursor = conn.execute(
                    f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
                    tuple(values),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None
        return self.get_session(session_id)

    def delete_session(self, session_id: str):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

db = DatabaseManager()
