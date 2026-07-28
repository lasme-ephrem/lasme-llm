from __future__ import annotations

import datetime
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

from core.memory.database import DB_PATH

try:
    from docx import Document as WordDocument
except ImportError:  # pragma: no cover - dependency is validated at startup
    WordDocument = None

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None

try:
    from pptx import Presentation
except ImportError:  # pragma: no cover
    Presentation = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


def _configure_tesseract() -> Optional[str]:
    if pytesseract is None:
        return None
    configured = os.getenv("TESSERACT_CMD", "").strip()
    candidates = [
        configured,
        shutil.which("tesseract") or "",
        "C:/Program Files/Tesseract-OCR/tesseract.exe",
        "C:/Program Files (x86)/Tesseract-OCR/tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate
    return None


_TESSERACT_COMMAND = _configure_tesseract()


MAX_PDF_PAGES = 300
MAX_PDF_VISION_PAGES = 40
MAX_TEXT_CHARS = 2_000_000
CHUNK_SIZE = 1_600
CHUNK_OVERLAP = 220
EMBEDDING_DIMENSIONS = 192
SUMMARY_INTENT_PATTERN = re.compile(
    r"\b(résum|resume|synthèse|synthese|vue d['’]ensemble|"
    r"tout le document|présente ce document|présente le document|"
    r"analyse globale|points clés|points cles)\b",
    flags=re.IGNORECASE,
)


class RAGDocumentStore:
    """Persistent hybrid retrieval with lexical and local vector ranking."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    @staticmethod
    @lru_cache(maxsize=1)
    def ocr_capabilities() -> Dict[str, Any]:
        if pytesseract is None or not _TESSERACT_COMMAND:
            return {
                "available": False,
                "engine": "tesseract",
                "command": "",
                "languages": [],
                "reason": "tesseract_not_installed",
            }
        try:
            languages = sorted(pytesseract.get_languages(config=""))
        except (OSError, RuntimeError, pytesseract.TesseractError):
            return {
                "available": False,
                "engine": "tesseract",
                "command": _TESSERACT_COMMAND,
                "languages": [],
                "reason": "tesseract_unavailable",
            }
        required = {"eng", "fra"}
        preferred_language = (
            "fra+eng"
            if required.issubset(languages)
            else ("fra" if "fra" in languages else ("eng" if "eng" in languages else ""))
        )
        return {
            "available": bool(preferred_language),
            "engine": "tesseract",
            "command": _TESSERACT_COMMAND,
            "languages": languages,
            "preferred_language": preferred_language,
            "french_ready": "fra" in languages,
            "english_ready": "eng" in languages,
            "reason": (
                ""
                if preferred_language
                else "language_data_missing"
            ),
        }

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
                    file_id TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    page_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'ready',
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
                    section_title TEXT NOT NULL DEFAULT '',
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
            if "file_id" not in document_columns:
                conn.execute("ALTER TABLE rag_documents ADD COLUMN file_id TEXT")
            if "mime_type" not in document_columns:
                conn.execute(
                    "ALTER TABLE rag_documents ADD COLUMN "
                    "mime_type TEXT NOT NULL DEFAULT ''"
                )
            if "status" not in document_columns:
                conn.execute(
                    "ALTER TABLE rag_documents ADD COLUMN "
                    "status TEXT NOT NULL DEFAULT 'ready'"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_documents_file "
                "ON rag_documents(file_id)"
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
            if "section_title" not in chunk_columns:
                conn.execute(
                    "ALTER TABLE rag_chunks ADD COLUMN "
                    "section_title TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        normalized = unicodedata.normalize("NFKD", text.casefold())
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return [
            token
            for token in re.findall(r"[a-z0-9_-]{2,}", normalized)
            if token not in {
                "avec", "dans", "pour", "des", "les", "une", "que", "qui",
                "sur", "par", "est", "sont", "the", "and", "for", "from",
                "en", "de", "du", "un", "au", "aux", "ce", "cet", "cette",
                "ces", "son", "sa", "ses", "se", "nous", "vous", "ils",
                "elles", "leur", "leurs", "notre", "votre", "mais", "ou",
            }
        ]

    @staticmethod
    def _normalized_phrase(text: str) -> str:
        return " ".join(RAGDocumentStore._tokenize(text))

    @staticmethod
    def _extract_pages(
        filename: str,
        content: bytes,
    ) -> List[tuple[int, str, str]]:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF too large: maximum {MAX_PDF_PAGES} pages."
                )
            pages: List[tuple[int, str, str]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                try:
                    extracted = page.extract_text(extraction_mode="layout") or ""
                except (TypeError, ValueError):
                    extracted = page.extract_text() or ""
                if (
                    len(extracted.strip()) < 24
                    and pymupdf is not None
                    and Image is not None
                    and pytesseract is not None
                    and RAGDocumentStore.ocr_capabilities().get("available")
                ):
                    try:
                        pdf = pymupdf.open(stream=content, filetype="pdf")
                        rendered = pdf.load_page(page_number - 1).get_pixmap(
                            matrix=pymupdf.Matrix(1.8, 1.8),
                            alpha=False,
                        )
                        image = Image.open(io.BytesIO(rendered.tobytes("png")))
                        extracted = pytesseract.image_to_string(
                            image,
                            lang=RAGDocumentStore.ocr_capabilities().get(
                                "preferred_language",
                                "eng",
                            ),
                        )
                        pdf.close()
                    except (
                        OSError,
                        RuntimeError,
                        ValueError,
                        pytesseract.TesseractNotFoundError,
                        pytesseract.TesseractError,
                    ):
                        pass
                if extracted.strip():
                    first_line = next(
                        (
                            line.strip()
                            for line in extracted.splitlines()
                            if 3 <= len(line.strip()) <= 140
                        ),
                        "",
                    )
                    pages.append((page_number, first_line, extracted))
        elif suffix == ".docx":
            if WordDocument is None:
                raise ValueError(
                    "Word support is not installed. Install python-docx."
                )
            document = WordDocument(io.BytesIO(content))
            sections: List[tuple[int, str, str]] = []
            current_title = "Document"
            current_lines: List[str] = []

            def flush_section() -> None:
                nonlocal current_lines
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(
                        (len(sections) + 1, current_title, text)
                    )
                current_lines = []

            for paragraph in document.paragraphs:
                text = paragraph.text.strip()
                if not text:
                    continue
                style_name = str(paragraph.style.name or "").casefold()
                if style_name.startswith(("heading", "titre")):
                    flush_section()
                    current_title = text[:140]
                else:
                    current_lines.append(text)
            for table_index, table in enumerate(document.tables, start=1):
                rows = [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in table.rows
                ]
                if rows:
                    current_lines.extend(
                        [f"Tableau {table_index}", *rows]
                    )
            flush_section()
            pages = sections
        elif suffix == ".xlsx":
            if load_workbook is None:
                raise ValueError(
                    "Excel support is not installed. Install openpyxl."
                )
            workbook = load_workbook(
                io.BytesIO(content),
                read_only=True,
                data_only=False,
            )
            pages = []
            for sheet_index, sheet in enumerate(workbook.worksheets, start=1):
                lines: List[str] = []
                for row in sheet.iter_rows(values_only=True):
                    values = [
                        "" if value is None else str(value)
                        for value in row
                    ]
                    if any(value.strip() for value in values):
                        lines.append("\t".join(values).rstrip())
                if lines:
                    pages.append(
                        (sheet_index, sheet.title[:140], "\n".join(lines))
                    )
        elif suffix == ".pptx":
            if Presentation is None:
                raise ValueError(
                    "PowerPoint support is not installed. Install python-pptx."
                )
            presentation = Presentation(io.BytesIO(content))
            pages = []
            for slide_number, slide in enumerate(
                presentation.slides,
                start=1,
            ):
                lines: List[str] = []
                title = f"Diapositive {slide_number}"
                if slide.shapes.title and slide.shapes.title.text.strip():
                    title = slide.shapes.title.text.strip()[:140]
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False):
                        text = shape.text.strip()
                        if text and text not in lines:
                            lines.append(text)
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            lines.append(
                                " | ".join(
                                    cell.text.strip()
                                    for cell in row.cells
                                )
                            )
                try:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                except (AttributeError, ValueError):
                    notes = ""
                if notes:
                    lines.append(f"Notes : {notes}")
                if lines:
                    pages.append(
                        (slide_number, title, "\n".join(lines))
                    )
        elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            ocr = RAGDocumentStore.ocr_capabilities()
            if (
                Image is None
                or pytesseract is None
                or not ocr.get("available")
            ):
                raise ValueError(
                    "Image OCR is not available. Configure a vision model "
                    "or install the local OCR dependencies."
                )
            image = Image.open(io.BytesIO(content))
            extracted = pytesseract.image_to_string(
                image,
                lang=ocr.get("preferred_language", "eng"),
            )
            pages = [(1, "Image", extracted)] if extracted.strip() else []
        elif suffix in {".txt", ".md"}:
            text = content.decode("utf-8", errors="replace")
            pages = [(1, Path(filename).stem[:140], text)]
        else:
            raise ValueError(
                "Supported documents are PDF, TXT, Markdown, Word, Excel, "
                "PowerPoint and OCR-compatible images."
            )

        text = "\n\n".join(page_text for _, _, page_text in pages)
        text = text.replace("\x00", " ").strip()
        if not text:
            raise ValueError("The document contains no extractable text.")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(
                f"Extracted text exceeds the {MAX_TEXT_CHARS:,}-character limit."
            )
        return [
            (
                page_number,
                section_title,
                page_text.replace("\x00", " ").strip(),
            )
            for page_number, section_title, page_text in pages
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

    def add_document(
        self,
        scope_id: str,
        filename: str,
        content: bytes,
        *,
        file_id: Optional[str] = None,
        mime_type: str = "",
    ) -> int:
        scope = (scope_id or "").strip()
        if not scope:
            raise ValueError("A document scope is required.")
        safe_filename = Path(filename or "document").name
        pages = self._extract_pages(safe_filename, content)
        return self._store_pages(
            scope,
            safe_filename,
            pages,
            file_id=file_id,
            mime_type=mime_type,
        )

    def add_extracted_text(
        self,
        scope_id: str,
        filename: str,
        text: str,
        *,
        file_id: Optional[str] = None,
        mime_type: str = "text/plain",
        section_title: str = "Analyse visuelle",
    ) -> int:
        scope = (scope_id or "").strip()
        normalized_text = str(text or "").replace("\x00", " ").strip()
        if not scope:
            raise ValueError("A document scope is required.")
        if not normalized_text:
            raise ValueError("The document contains no extractable text.")
        if len(normalized_text) > MAX_TEXT_CHARS:
            raise ValueError("Extracted text exceeds the configured limit.")
        return self._store_pages(
            scope,
            Path(filename or "document").name,
            [(1, section_title[:140], normalized_text)],
            file_id=file_id,
            mime_type=mime_type,
        )

    def add_extracted_pages(
        self,
        scope_id: str,
        filename: str,
        pages: List[tuple[int, str, str]],
        *,
        file_id: Optional[str] = None,
        mime_type: str = "application/pdf",
    ) -> int:
        scope = (scope_id or "").strip()
        normalized_pages = [
            (
                max(1, int(page_number)),
                str(title or "Analyse visuelle")[:140],
                str(text or "").replace("\x00", " ").strip(),
            )
            for page_number, title, text in pages
            if str(text or "").strip()
        ]
        if not scope:
            raise ValueError("A document scope is required.")
        if not normalized_pages:
            raise ValueError("The document contains no extractable text.")
        return self._store_pages(
            scope,
            Path(filename or "document").name,
            normalized_pages,
            file_id=file_id,
            mime_type=mime_type,
        )

    def append_extracted_pages(
        self,
        document_id: str,
        pages: List[tuple[int, str, str]],
    ) -> int:
        normalized_pages = [
            (
                max(1, int(page_number)),
                str(title or "Analyse visuelle")[:140],
                str(text or "").replace("\x00", " ").strip(),
            )
            for page_number, title, text in pages
            if str(text or "").strip()
        ]
        if not normalized_pages:
            return 0
        chunks: List[tuple[int, int, str, str]] = []
        for page_number, title, text in normalized_pages:
            start_char = 0
            for chunk in self._chunk_text(text):
                chunks.append((page_number, start_char, title, chunk))
                start_char += max(1, len(chunk) - CHUNK_OVERLAP)
        with self._connection() as conn:
            document = conn.execute(
                "SELECT id, page_count FROM rag_documents "
                "WHERE id = ? OR file_id = ? LIMIT 1",
                (document_id, document_id),
            ).fetchone()
            if not document:
                raise ValueError("Indexed document not found.")
            position_row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) AS position "
                "FROM rag_chunks WHERE document_id = ?",
                (document["id"],),
            ).fetchone()
            start_position = int(position_row["position"]) + 1
            conn.executemany(
                """
                INSERT INTO rag_chunks
                    (id, document_id, position, page_number, start_char,
                     section_title, content, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        document["id"],
                        start_position + index,
                        page_number,
                        start_char,
                        title,
                        chunk,
                        json.dumps(
                            self._embedding(chunk),
                            separators=(",", ":"),
                        ),
                    )
                    for index, (
                        page_number,
                        start_char,
                        title,
                        chunk,
                    ) in enumerate(chunks)
                ],
            )
            conn.execute(
                "UPDATE rag_documents SET page_count = ? WHERE id = ?",
                (
                    max(
                        int(document["page_count"] or 0),
                        max(page[0] for page in normalized_pages),
                    ),
                    document["id"],
                ),
            )
        return len(chunks)

    @staticmethod
    def render_pdf_pages_for_vision(
        content: bytes,
        *,
        max_pages: int = MAX_PDF_VISION_PAGES,
    ) -> tuple[List[tuple[int, bytes, str]], int]:
        """Render scanned or visually rich PDF pages for the local VLM."""
        if pymupdf is None:
            raise ValueError("PyMuPDF is required for visual PDF analysis.")
        rendered: List[tuple[int, bytes, str]] = []
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            total_pages = len(pdf)
            for page_index in range(total_pages):
                if len(rendered) >= max(1, min(max_pages, MAX_PDF_VISION_PAGES)):
                    break
                page = pdf.load_page(page_index)
                text = page.get_text("text").strip()
                page_area = max(1.0, float(page.rect.width * page.rect.height))
                image_area = 0.0
                try:
                    for image_info in page.get_image_info():
                        bbox = image_info.get("bbox")
                        if bbox and len(bbox) == 4:
                            image_area = max(
                                image_area,
                                max(0.0, float(bbox[2] - bbox[0]))
                                * max(0.0, float(bbox[3] - bbox[1])),
                            )
                except (RuntimeError, ValueError):
                    image_area = 0.0
                try:
                    drawing_count = len(page.get_drawings())
                except (RuntimeError, ValueError):
                    drawing_count = 0
                scanned = len(text) < 24
                visually_rich = (
                    image_area / page_area >= 0.15
                    or drawing_count >= 20
                )
                if not scanned and not visually_rich:
                    continue
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(1.55, 1.55),
                    alpha=False,
                )
                rendered.append(
                    (
                        page_index + 1,
                        pixmap.tobytes("png"),
                        "scan" if scanned else "visual",
                    )
                )
        return rendered, total_pages

    def _store_pages(
        self,
        scope: str,
        safe_filename: str,
        pages: List[tuple[int, str, str]],
        *,
        file_id: Optional[str],
        mime_type: str,
    ) -> int:
        chunks: List[tuple[int, int, str, str]] = []
        for page_number, section_title, page_text in pages:
            start_char = 0
            for chunk in self._chunk_text(page_text):
                chunks.append(
                    (page_number, start_char, section_title, chunk)
                )
                start_char += max(1, len(chunk) - CHUNK_OVERLAP)
        document_id = file_id or str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._connection() as conn:
            if file_id:
                existing = conn.execute(
                    "SELECT id FROM rag_documents WHERE file_id = ?",
                    (file_id,),
                ).fetchone()
                if existing:
                    conn.execute(
                        "DELETE FROM rag_documents WHERE id = ?",
                        (existing["id"],),
                    )
            conn.execute(
                """
                INSERT INTO rag_documents
                    (id, scope_id, file_id, filename, mime_type,
                     page_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'ready', ?)
                """,
                (
                    document_id,
                    scope,
                    file_id,
                    safe_filename,
                    mime_type,
                    len(pages),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO rag_chunks
                    (id, document_id, position, page_number, start_char,
                     section_title, content, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        document_id,
                        index,
                        page_number,
                        start_char,
                        section_title,
                        chunk,
                        json.dumps(self._embedding(chunk), separators=(",", ":")),
                    )
                    for index, (
                        page_number,
                        start_char,
                        section_title,
                        chunk,
                    ) in enumerate(chunks)
                ],
            )
        return len(chunks)

    def preview(
        self,
        filename: str,
        content: bytes,
        *,
        max_sections: int = 80,
        max_chars_per_section: int = 12_000,
    ) -> List[Dict[str, Any]]:
        pages = self._extract_pages(filename, content)
        return [
            {
                "page": page_number,
                "title": section_title,
                "text": text[:max_chars_per_section],
                "truncated": len(text) > max_chars_per_section,
            }
            for page_number, section_title, text in pages[:max_sections]
        ]

    def search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 4,
        file_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        scope = (scope_id or "").strip()
        query_terms = self._tokenize(query)
        if not scope or not query_terms:
            return []

        with self._connection() as conn:
            query_sql = """
                SELECT d.id AS document_id, d.file_id, d.filename AS doc_name,
                       c.id AS chunk_id, c.position, c.page_number,
                       c.start_char, c.section_title, c.content, c.embedding
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                WHERE d.scope_id = ?
            """
            params: List[Any] = [scope]
            normalized_file_ids = [
                str(file_id).strip()
                for file_id in (file_ids or [])
                if str(file_id).strip()
            ]
            if normalized_file_ids:
                placeholders = ",".join("?" for _ in normalized_file_ids)
                query_sql += (
                    f" AND (d.file_id IN ({placeholders}) "
                    f"OR d.id IN ({placeholders}))"
                )
                params.extend(normalized_file_ids)
                params.extend(normalized_file_ids)
            query_sql += " ORDER BY d.created_at, c.position"
            rows = conn.execute(query_sql, tuple(params)).fetchall()
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
        query_phrase = self._normalized_phrase(query)
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
            content_overlap = len(set(tokens).intersection(query_terms))
            section_tokens = set(
                self._tokenize(row["section_title"] or "")
            )
            section_overlap = len(section_tokens.intersection(query_terms))
            if section_overlap:
                lexical_score += 1.2 * section_overlap
            filename_overlap = len(
                set(self._tokenize(row["doc_name"] or "")).intersection(query_terms)
            )
            lexical_score += 0.7 * filename_overlap
            content_phrase = self._normalized_phrase(
                f"{row['section_title']} {row['content']}"
            )
            phrase_bonus = (
                1.5
                if len(query_phrase) >= 8 and query_phrase in content_phrase
                else 0.0
            )
            lexical_score += phrase_bonus
            # Normalize BM25 into a bounded range before fusion. Lexical
            # precision leads. The local feature hash is useful for ranking,
            # but is not a semantic embedding and must never admit an
            # unrelated chunk on its own at a tiny score.
            lexical_normalized = lexical_score / (lexical_score + 3.0)
            hybrid_score = 0.85 * lexical_normalized + 0.15 * vector_score
            has_lexical_evidence = bool(
                content_overlap
                or section_overlap
                or filename_overlap
                or phrase_bonus
            )
            has_strong_feature_evidence = vector_score >= 0.38
            if (
                (has_lexical_evidence or has_strong_feature_evidence)
                and hybrid_score > 0.05
            ):
                scored.append(
                    (
                        hybrid_score,
                        {
                            "document_id": row["document_id"],
                            "file_id": row["file_id"],
                            "chunk_id": row["chunk_id"],
                            "doc_name": row["doc_name"],
                            "page": row["page_number"],
                            "position": row["position"],
                            "start_char": row["start_char"],
                            "section": row["section_title"],
                            "content": row["content"],
                            "score": round(hybrid_score, 4),
                            "lexical_score": round(lexical_score, 4),
                            "vector_score": round(vector_score, 4),
                            "lexical_overlap": content_overlap,
                        },
                    )
                )

        scored.sort(key=lambda item: item[0], reverse=True)
        limit = max(1, min(top_k, 10))
        selected: List[tuple[float, Dict[str, Any]]] = []
        candidates = scored[: max(limit * 5, limit)]
        while candidates and len(selected) < limit:
            best_index = 0
            best_value = float("-inf")
            for index, (relevance, candidate) in enumerate(candidates):
                redundancy = 0.0
                candidate_tokens = set(self._tokenize(candidate["content"]))
                for _, chosen in selected:
                    chosen_tokens = set(self._tokenize(chosen["content"]))
                    union = candidate_tokens.union(chosen_tokens)
                    similarity = (
                        len(candidate_tokens.intersection(chosen_tokens)) / len(union)
                        if union
                        else 0.0
                    )
                    if (
                        candidate["document_id"] == chosen["document_id"]
                        and abs(int(candidate["position"]) - int(chosen["position"])) <= 1
                    ):
                        similarity = max(similarity, 0.72)
                    redundancy = max(redundancy, similarity)
                mmr = 0.82 * relevance - 0.18 * redundancy
                if mmr > best_value:
                    best_index = index
                    best_value = mmr
            selected.append(candidates.pop(best_index))
        return [item[1] for item in selected]

    def search_scopes(
        self,
        scope_ids: List[str],
        query: str,
        top_k: int = 6,
        file_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if SUMMARY_INTENT_PATTERN.search(query or ""):
            return self.overview_scopes(
                scope_ids,
                file_ids=file_ids,
                max_chunks=max(8, min(top_k * 2, 18)),
            )
        merged: Dict[str, Dict[str, Any]] = {}
        for scope_id in dict.fromkeys(scope_ids):
            for result in self.search(
                scope_id,
                query,
                top_k=top_k,
                file_ids=file_ids,
            ):
                result["scope_id"] = scope_id
                existing = merged.get(result["chunk_id"])
                if not existing or result["score"] > existing["score"]:
                    merged[result["chunk_id"]] = result
        return sorted(
            merged.values(),
            key=lambda item: item["score"],
            reverse=True,
        )[: max(1, min(top_k, 12))]

    def overview_scopes(
        self,
        scope_ids: List[str],
        *,
        file_ids: Optional[List[str]] = None,
        max_chunks: int = 16,
    ) -> List[Dict[str, Any]]:
        """Return representative chunks across the full selected documents."""
        normalized_scopes = [
            str(scope).strip()
            for scope in dict.fromkeys(scope_ids)
            if str(scope).strip()
        ]
        if not normalized_scopes:
            return []
        scope_placeholders = ",".join("?" for _ in normalized_scopes)
        sql = f"""
            SELECT d.id AS document_id, d.file_id, d.filename AS doc_name,
                   c.id AS chunk_id, c.position, c.page_number,
                   c.start_char, c.section_title, c.content
            FROM rag_chunks c
            JOIN rag_documents d ON d.id = c.document_id
            WHERE d.scope_id IN ({scope_placeholders})
        """
        params: List[Any] = list(normalized_scopes)
        normalized_file_ids = [
            str(file_id).strip()
            for file_id in (file_ids or [])
            if str(file_id).strip()
        ]
        if normalized_file_ids:
            placeholders = ",".join("?" for _ in normalized_file_ids)
            sql += (
                f" AND (d.file_id IN ({placeholders}) "
                f"OR d.id IN ({placeholders}))"
            )
            params.extend(normalized_file_ids)
            params.extend(normalized_file_ids)
        sql += " ORDER BY d.created_at, c.position"
        with self._connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        if not rows:
            return []

        grouped: Dict[str, List[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["document_id"], []).append(row)
        selected: List[sqlite3.Row] = []
        per_document = max(2, max_chunks // max(1, len(grouped)))
        for document_rows in grouped.values():
            if len(document_rows) <= per_document:
                selected.extend(document_rows)
                continue
            indexes = {
                round(index * (len(document_rows) - 1) / (per_document - 1))
                for index in range(per_document)
            }
            selected.extend(document_rows[index] for index in sorted(indexes))
        selected = selected[:max_chunks]
        return [
            {
                "document_id": row["document_id"],
                "file_id": row["file_id"],
                "chunk_id": row["chunk_id"],
                "doc_name": row["doc_name"],
                "page": row["page_number"],
                "position": row["position"],
                "start_char": row["start_char"],
                "section": row["section_title"],
                "content": row["content"],
                "score": 1.0,
                "coverage": True,
            }
            for row in selected
        ]

    def list_documents(self, scope_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.scope_id, d.file_id, d.filename, d.mime_type,
                       d.page_count, d.status, d.created_at,
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

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT d.id, d.scope_id, d.file_id, d.filename, d.mime_type,
                       d.page_count, d.status, d.created_at,
                       COUNT(c.id) AS chunk_count
                FROM rag_documents d
                LEFT JOIN rag_chunks c ON c.document_id = d.id
                WHERE d.id = ?
                GROUP BY d.id
                """,
                ((document_id or "").strip(),),
            ).fetchone()
        return dict(row) if row else None

    def preview_indexed_document(
        self,
        document_id: str,
        *,
        max_sections: int = 80,
        max_chars_per_section: int = 12_000,
    ) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT page_number, section_title, content
                FROM rag_chunks
                WHERE document_id = ?
                ORDER BY position
                LIMIT ?
                """,
                ((document_id or "").strip(), max(1, min(max_sections, 200))),
            ).fetchall()
        return [
            {
                "page": int(row["page_number"] or 1),
                "title": row["section_title"] or "Passage indexé",
                "text": str(row["content"] or "")[:max_chars_per_section],
                "truncated": len(str(row["content"] or ""))
                > max_chars_per_section,
            }
            for row in rows
        ]

    def rename_document(self, document_id: str, filename: str) -> bool:
        safe_name = Path(filename or "").name.strip()[:180]
        if not safe_name:
            raise ValueError("A document name is required.")
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE rag_documents SET filename = ? WHERE id = ?",
                (safe_name, (document_id or "").strip()),
            )
            return cursor.rowcount > 0

    def delete_document(self, document_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM rag_documents WHERE id = ? OR file_id = ?",
                (document_id, document_id),
            )
            return cursor.rowcount > 0

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
