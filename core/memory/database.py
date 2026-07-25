import sqlite3
import uuid
import datetime
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
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
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
            conn.commit()

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
            cursor.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

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

    def add_message(self, session_id: str, role: str, content: str):
        msg_id = str(uuid.uuid4())
        now = datetime.datetime.now().isoformat()
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
                "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, now)
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
