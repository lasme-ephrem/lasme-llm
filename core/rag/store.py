from __future__ import annotations

import datetime
import io
import math
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

from pypdf import PdfReader

from core.memory.database import DB_PATH


MAX_PDF_PAGES = 200
MAX_TEXT_CHARS = 2_000_000
CHUNK_SIZE = 1_200
CHUNK_OVERLAP = 150


class RAGDocumentStore:
    """Persistent, conversation-scoped document retrieval using local BM25."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rag_documents_scope
                    ON rag_documents(scope_id);

                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY (document_id)
                        REFERENCES rag_documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
                    ON rag_chunks(document_id, position);
                """
            )

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [
            token
            for token in re.findall(r"[a-zA-ZÀ-ÿ0-9_-]{2,}", text.lower())
            if token not in {
                "avec", "dans", "pour", "des", "les", "une", "que", "qui",
                "sur", "par", "est", "sont", "the", "and", "for", "from",
            }
        ]

    @staticmethod
    def _extract_text(filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF too large: maximum {MAX_PDF_PAGES} pages."
                )
            pages = []
            for page in reader.pages:
                extracted = page.extract_text() or ""
                if extracted.strip():
                    pages.append(extracted)
            text = "\n\n".join(pages)
        elif suffix in {".txt", ".md"}:
            text = content.decode("utf-8", errors="replace")
        else:
            raise ValueError("Only PDF, TXT and Markdown documents are supported.")

        text = text.replace("\x00", " ").strip()
        if not text:
            raise ValueError("The document contains no extractable text.")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(
                f"Extracted text exceeds the {MAX_TEXT_CHARS:,}-character limit."
            )
        return text

    @staticmethod
    def _chunk_text(text: str) -> List[str]:
        chunks: List[str] = []
        start = 0
        while start < len(text):
            proposed_end = min(len(text), start + CHUNK_SIZE)
            end = proposed_end
            if proposed_end < len(text):
                boundary = max(
                    text.rfind("\n", start + CHUNK_SIZE // 2, proposed_end),
                    text.rfind(" ", start + CHUNK_SIZE // 2, proposed_end),
                )
                if boundary > start:
                    end = boundary
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(start + 1, end - CHUNK_OVERLAP)
        return chunks

    def add_document(self, scope_id: str, filename: str, content: bytes) -> int:
        scope = (scope_id or "").strip()
        if not scope:
            raise ValueError("A document scope is required.")
        safe_filename = Path(filename or "document").name
        text = self._extract_text(safe_filename, content)
        chunks = self._chunk_text(text)
        document_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO rag_documents (id, scope_id, filename, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, scope, safe_filename, now),
            )
            conn.executemany(
                """
                INSERT INTO rag_chunks (id, document_id, position, content)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (str(uuid.uuid4()), document_id, index, chunk)
                    for index, chunk in enumerate(chunks)
                ],
            )
        return len(chunks)

    def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 4,
    ) -> List[Dict[str, Any]]:
        scope = (scope_id or "").strip()
        query_terms = self._tokenize(query)
        if not scope or not query_terms:
            return []

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT d.filename AS doc_name, c.content
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                WHERE d.scope_id = ?
                ORDER BY d.created_at, c.position
                """,
                (scope,),
            ).fetchall()
        if not rows:
            return []

        documents = [self._tokenize(row["content"]) for row in rows]
        average_length = sum(len(tokens) for tokens in documents) / len(documents)
        document_frequency = Counter()
        for tokens in documents:
            document_frequency.update(set(tokens))

        k1 = 1.5
        b = 0.75
        scored = []
        for row, tokens in zip(rows, documents):
            frequencies = Counter(tokens)
            length = max(1, len(tokens))
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency.get(term, 0)
                idf = math.log(1 + (len(rows) - df + 0.5) / (df + 0.5))
                denominator = frequency + k1 * (
                    1 - b + b * length / max(1.0, average_length)
                )
                score += idf * (frequency * (k1 + 1)) / denominator
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "doc_name": row["doc_name"],
                            "content": row["content"],
                            "score": round(score, 4),
                        },
                    )
                )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, min(top_k, 10))]]

    def clear(self, scope_id: str) -> int:
        scope = (scope_id or "").strip()
        if not scope:
            return 0
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM rag_documents WHERE scope_id = ?",
                (scope,),
            )
            return cursor.rowcount

    def move_scope(self, source_scope_id: str, target_scope_id: str) -> int:
        source = (source_scope_id or "").strip()
        target = (target_scope_id or "").strip()
        if not source or not target or source == target:
            return 0
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE rag_documents SET scope_id = ? WHERE scope_id = ?",
                (target, source),
            )
            return cursor.rowcount

    def count_chunks(self, scope_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                WHERE d.scope_id = ?
                """,
                ((scope_id or "").strip(),),
            ).fetchone()
        return int(row["count"] if row else 0)


rag_store = RAGDocumentStore()
