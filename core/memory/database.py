import sqlite3
import uuid
import datetime
import json
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "lasme_llm.db"

class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

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
            message_columns = {
                row["name"]
                for row in cursor.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "metadata" not in message_columns:
                cursor.execute(
                    "ALTER TABLE messages ADD COLUMN "
                    "metadata TEXT NOT NULL DEFAULT '{}'"
                )
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

    def create_session(self, title: str = "Nouvelle Conversation", model: str = "gemma-4-chat") -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, model, now, now)
            )
            conn.commit()
        return {"id": session_id, "title": title, "model": model, "created_at": now}

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content, metadata, timestamp
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
    ):
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
                    "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, "Nouvelle Conversation", "gemma-4-chat", now, now)
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

    def update_session_title(self, session_id: str, title: str):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
            conn.commit()

    def delete_session(self, session_id: str):
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

db = DatabaseManager()
