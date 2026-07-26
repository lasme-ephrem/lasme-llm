from __future__ import annotations

import datetime
import hashlib
import io
import json
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
EMBEDDING_DIMENSIONS = 192


class RAGDocumentStore:
    """Persistent hybrid retrieval with lexical and local vector ranking."""

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
                    page_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rag_documents_scope
                    ON rag_documents(scope_id);

                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    page_number INTEGER,
                    start_char INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (document_id)
                        REFERENCES rag_documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
                    ON rag_chunks(document_id, position);
                """
            )
            document_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(rag_documents)").fetchall()
            }
            if "page_count" not in document_columns:
                conn.execute(
                    "ALTER TABLE rag_documents ADD COLUMN "
                    "page_count INTEGER NOT NULL DEFAULT 1"
                )
            chunk_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()
            }
            if "page_number" not in chunk_columns:
                conn.execute("ALTER TABLE rag_chunks ADD COLUMN page_number INTEGER")
            if "start_char" not in chunk_columns:
                conn.execute(
                    "ALTER TABLE rag_chunks ADD COLUMN "
                    "start_char INTEGER NOT NULL DEFAULT 0"
                )
            if "embedding" not in chunk_columns:
                conn.execute(
                    "ALTER TABLE rag_chunks ADD COLUMN "
                    "embedding TEXT NOT NULL DEFAULT '[]'"
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
    def _extract_pages(filename: str, content: bytes) -> List[tuple[int, str]]:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF too large: maximum {MAX_PDF_PAGES} pages."
                )
            pages: List[tuple[int, str]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                extracted = page.extract_text() or ""
                if extracted.strip():
                    pages.append((page_number, extracted))
        elif suffix in {".txt", ".md"}:
            pages = [(1, content.decode("utf-8", errors="replace"))]
        else:
            raise ValueError("Only PDF, TXT and Markdown documents are supported.")

        text = "\n\n".join(page_text for _, page_text in pages)
        text = text.replace("\x00", " ").strip()
        if not text:
            raise ValueError("The document contains no extractable text.")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(
                f"Extracted text exceeds the {MAX_TEXT_CHARS:,}-character limit."
            )
        return [
            (page_number, page_text.replace("\x00", " ").strip())
            for page_number, page_text in pages
            if page_text.strip()
        ]

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

    @staticmethod
    def _embedding(text: str) -> List[float]:
        """Create a deterministic local feature embedding without a model download.

        Word features preserve topic terms while character trigrams make the
        vector tolerant to accents, inflections and minor spelling differences.
        """
        normalized = " ".join(text.casefold().split())
        features = RAGDocumentStore._tokenize(normalized)
        compact = re.sub(r"\s+", " ", normalized)
        features.extend(
            f"#{compact[index:index + 3]}"
            for index in range(max(0, len(compact) - 2))
        )
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for feature in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8"),
                digest_size=8,
            ).digest()
            bucket = int.from_bytes(digest[:4], "little") % EMBEDDING_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [round(value / norm, 6) for value in vector]
        return vector

    @staticmethod
    def _cosine(left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))

    def add_document(self, scope_id: str, filename: str, content: bytes) -> int:
        scope = (scope_id or "").strip()
        if not scope:
            raise ValueError("A document scope is required.")
        safe_filename = Path(filename or "document").name
        pages = self._extract_pages(safe_filename, content)
        chunks: List[tuple[int, int, str]] = []
        for page_number, page_text in pages:
            start_char = 0
            for chunk in self._chunk_text(page_text):
                chunks.append((page_number, start_char, chunk))
                start_char += max(1, len(chunk) - CHUNK_OVERLAP)
        document_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO rag_documents
                    (id, scope_id, filename, page_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (document_id, scope, safe_filename, len(pages), now),
            )
            conn.executemany(
                """
                INSERT INTO rag_chunks
                    (id, document_id, position, page_number, start_char,
                     content, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        document_id,
                        index,
                        page_number,
                        start_char,
                        chunk,
                        json.dumps(self._embedding(chunk), separators=(",", ":")),
                    )
                    for index, (page_number, start_char, chunk) in enumerate(chunks)
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
                SELECT d.id AS document_id, d.filename AS doc_name,
                       c.id AS chunk_id, c.position, c.page_number,
                       c.start_char, c.content, c.embedding
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
        query_embedding = self._embedding(query)
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
            try:
                stored_embedding = json.loads(row["embedding"] or "[]")
            except (TypeError, ValueError):
                stored_embedding = []
            if not stored_embedding:
                stored_embedding = self._embedding(row["content"])
            vector_score = max(0.0, self._cosine(query_embedding, stored_embedding))
            lexical_score = score
            # Normalize BM25 into a bounded range before fusion. Lexical
            # precision leads; vector similarity recovers paraphrases.
            lexical_normalized = lexical_score / (lexical_score + 3.0)
            hybrid_score = 0.68 * lexical_normalized + 0.32 * vector_score
            if hybrid_score > 0.035:
                scored.append(
                    (
                        hybrid_score,
                        {
                            "document_id": row["document_id"],
                            "chunk_id": row["chunk_id"],
                            "doc_name": row["doc_name"],
                            "page": row["page_number"],
                            "position": row["position"],
                            "start_char": row["start_char"],
                            "content": row["content"],
                            "score": round(hybrid_score, 4),
                            "lexical_score": round(lexical_score, 4),
                            "vector_score": round(vector_score, 4),
                        },
                    )
                )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, min(top_k, 10))]]

    def search_scopes(
        self,
        scope_ids: List[str],
        query: str,
        top_k: int = 6,
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for scope_id in dict.fromkeys(scope_ids):
            for result in self.search(scope_id, query, top_k=top_k):
                result["scope_id"] = scope_id
                existing = merged.get(result["chunk_id"])
                if not existing or result["score"] > existing["score"]:
                    merged[result["chunk_id"]] = result
        return sorted(
            merged.values(),
            key=lambda item: item["score"],
            reverse=True,
        )[: max(1, min(top_k, 12))]

    def list_documents(self, scope_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.filename, d.page_count, d.created_at,
                       COUNT(c.id) AS chunk_count
                FROM rag_documents d
                LEFT JOIN rag_chunks c ON c.document_id = d.id
                WHERE d.scope_id = ?
                GROUP BY d.id
                ORDER BY d.created_at DESC
                """,
                ((scope_id or "").strip(),),
            ).fetchall()
        return [dict(row) for row in rows]

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
