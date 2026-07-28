from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import shutil
import sqlite3
import uuid
import warnings
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, UnidentifiedImageError

from core.memory.database import DB_PATH, DEFAULT_PROJECT_ID


PROJECT_FILES_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / ".runtime"
    / "project_files"
)

ALLOWED_FILE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".docx",
    ".xlsx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

FILE_KIND_BY_EXTENSION = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
    ".docx": "word",
    ".xlsx": "spreadsheet",
    ".pptx": "presentation",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}

CANONICAL_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

OFFICE_ARCHIVE_PREFIXES = {
    ".docx": "word/",
    ".xlsx": "xl/",
    ".pptx": "ppt/",
}

MAX_OFFICE_ARCHIVE_MEMBERS = 5_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_OFFICE_COMPRESSION_RATIO = 100


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_filename(filename: str) -> str:
    candidate = Path(filename or "document").name.strip()
    if not candidate:
        candidate = "document"
    sanitized = "".join(
        char if char.isalnum() or char in "._- ()" else "_"
        for char in candidate
    ).strip(" .")
    return sanitized[:180] or "document"


def canonical_mime_type(extension: str) -> str:
    """Return the server-owned MIME type for a supported extension."""
    return CANONICAL_MIME_TYPES.get(
        (extension or "").strip().lower(),
        "application/octet-stream",
    )


def _validate_office_archive(content: bytes, extension: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_OFFICE_ARCHIVE_MEMBERS:
                raise ValueError("Invalid or oversized Office archive.")
            total_uncompressed = sum(max(0, item.file_size) for item in members)
            total_compressed = sum(max(1, item.compress_size) for item in members)
            if total_uncompressed > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise ValueError("Office archive expands beyond the safe limit.")
            if (
                total_uncompressed > 10 * 1024 * 1024
                and total_uncompressed
                > total_compressed * MAX_OFFICE_COMPRESSION_RATIO
            ):
                raise ValueError("Suspicious Office archive compression ratio.")
            normalized_names = set()
            for item in members:
                if item.flag_bits & 0x1:
                    raise ValueError("Encrypted Office documents are not supported.")
                normalized = item.filename.replace("\\", "/").lstrip("/")
                parts = Path(normalized).parts
                if ".." in parts:
                    raise ValueError("Unsafe path found in Office archive.")
                normalized_names.add(normalized)
            expected_prefix = OFFICE_ARCHIVE_PREFIXES[extension]
            if (
                "[Content_Types].xml" not in normalized_names
                or not any(
                    name.startswith(expected_prefix)
                    for name in normalized_names
                )
            ):
                raise ValueError(
                    f"The uploaded file is not a valid {extension[1:].upper()} document."
                )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"The uploaded file is not a valid {extension[1:].upper()} document."
        ) from exc


def _validate_image(content: bytes, extension: str) -> None:
    expected_formats = {
        ".png": {"PNG"},
        ".jpg": {"JPEG"},
        ".jpeg": {"JPEG"},
        ".webp": {"WEBP"},
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                detected = (image.format or "").upper()
                if detected not in expected_formats[extension]:
                    raise ValueError(
                        "The image content does not match its file extension."
                    )
                image.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise ValueError("The uploaded image is invalid or unsafe.") from exc


def validate_file_content(extension: str, content: bytes) -> None:
    """Reject extension/content mismatches and common archive/image bombs."""
    normalized_extension = (extension or "").strip().lower()
    if normalized_extension == ".pdf":
        header = content[:1_024].lstrip(b"\x00\t\r\n \xef\xbb\xbf")
        if not header.startswith(b"%PDF-"):
            raise ValueError("The uploaded file is not a valid PDF document.")
        return
    if normalized_extension in OFFICE_ARCHIVE_PREFIXES:
        _validate_office_archive(content, normalized_extension)
        return
    if normalized_extension in {".png", ".jpg", ".jpeg", ".webp"}:
        _validate_image(content, normalized_extension)
        return
    if normalized_extension in {".txt", ".md"}:
        if b"\x00" in content:
            raise ValueError("Text documents cannot contain binary null bytes.")
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text documents must use UTF-8 encoding.") from exc
        return
    raise ValueError("Unsupported file type.")


class ProjectFileStore:
    """Durable originals and metadata for files attached to projects."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        storage_root: Path = PROJECT_FILES_ROOT,
    ):
        self.db_path = Path(db_path)
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS project_files (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'stored',
                    page_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_project_files_project
                    ON project_files(project_id, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_project_files_deduplicate
                    ON project_files(project_id, sha256);
                """
            )
            conn.execute(
                """
                UPDATE project_files
                SET status = 'error',
                    error = CASE
                        WHEN status = 'indexing'
                        THEN 'Indexation interrompue. Relancez la réindexation.'
                        ELSE 'Fichier stocké mais non indexé. Lancez la réindexation.'
                    END,
                    updated_at = ?
                WHERE status IN ('stored', 'indexing')
                """,
                (_utc_now(),),
            )

    @staticmethod
    def _serialize(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        try:
            result["metadata"] = json.loads(result.get("metadata") or "{}")
        except (TypeError, ValueError):
            result["metadata"] = {}
        result["size_bytes"] = int(result.get("size_bytes") or 0)
        result["page_count"] = int(result.get("page_count") or 0)
        result["chunk_count"] = int(result.get("chunk_count") or 0)
        result["mime_type"] = canonical_mime_type(result.get("extension", ""))
        result["preview_url"] = f"/api/files/{result['id']}/content"
        result["download_url"] = f"/api/files/{result['id']}/download"
        return result

    def list(self, project_id: str) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_files
                WHERE project_id = ?
                ORDER BY updated_at DESC, display_name COLLATE NOCASE
                """,
                ((project_id or DEFAULT_PROJECT_ID).strip(),),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def get(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM project_files WHERE id = ?",
                ((file_id or "").strip(),),
            ).fetchone()
        return self._serialize(row) if row else None

    def get_by_hash(
        self,
        project_id: str,
        sha256: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM project_files
                WHERE project_id = ? AND sha256 = ?
                """,
                (
                    (project_id or DEFAULT_PROJECT_ID).strip(),
                    (sha256 or "").strip().lower(),
                ),
            ).fetchone()
        return self._serialize(row) if row else None

    def add(
        self,
        *,
        project_id: str,
        filename: str,
        content: bytes,
        mime_type: str = "",
    ) -> tuple[Dict[str, Any], bool]:
        scope = (project_id or DEFAULT_PROJECT_ID).strip()
        safe_name = _safe_filename(filename)
        extension = Path(safe_name).suffix.lower()
        if extension not in ALLOWED_FILE_EXTENSIONS:
            supported = ", ".join(sorted(ALLOWED_FILE_EXTENSIONS))
            raise ValueError(f"Unsupported file type. Supported: {supported}.")
        if not content:
            raise ValueError("The uploaded file is empty.")
        validate_file_content(extension, content)

        digest = hashlib.sha256(content).hexdigest()
        duplicate = self.get_by_hash(scope, digest)
        if duplicate:
            return duplicate, True

        file_id = str(uuid.uuid4())
        relative_path = Path(scope) / file_id / safe_name
        absolute_path = (self.storage_root / relative_path).resolve()
        root = self.storage_root.resolve()
        try:
            absolute_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Invalid project file path.") from exc

        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = absolute_path.with_suffix(absolute_path.suffix + ".part")
        temporary_path.write_bytes(content)
        os.replace(temporary_path, absolute_path)

        # Never trust a client-controlled Content-Type. The MIME served later
        # is derived from the validated file extension and signature.
        resolved_mime = canonical_mime_type(extension)
        now = _utc_now()
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO project_files
                        (id, project_id, filename, display_name, extension,
                         mime_type, kind, size_bytes, sha256, storage_path,
                         status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'stored', ?, ?)
                    """,
                    (
                        file_id,
                        scope,
                        safe_name,
                        safe_name,
                        extension,
                        resolved_mime,
                        FILE_KIND_BY_EXTENSION[extension],
                        len(content),
                        digest,
                        relative_path.as_posix(),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            shutil.rmtree(absolute_path.parent, ignore_errors=True)
            concurrent_duplicate = self.get_by_hash(scope, digest)
            if concurrent_duplicate:
                return concurrent_duplicate, True
            raise
        except Exception:
            shutil.rmtree(absolute_path.parent, ignore_errors=True)
            raise
        return self.get(file_id) or {}, False

    def update(
        self,
        file_id: str,
        *,
        status: Optional[str] = None,
        page_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        updates: List[str] = []
        values: List[Any] = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if page_count is not None:
            updates.append("page_count = ?")
            values.append(max(0, int(page_count)))
        if chunk_count is not None:
            updates.append("chunk_count = ?")
            values.append(max(0, int(chunk_count)))
        if error is not None:
            updates.append("error = ?")
            values.append(str(error)[:1_000])
        if metadata is not None:
            updates.append("metadata = ?")
            values.append(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        if display_name is not None:
            normalized = _safe_filename(display_name)
            if not normalized:
                raise ValueError("A display name is required.")
            updates.append("display_name = ?")
            values.append(normalized)
        if not updates:
            return self.get(file_id)
        updates.append("updated_at = ?")
        values.extend([_utc_now(), file_id])
        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE project_files SET {', '.join(updates)} WHERE id = ?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(file_id)

    def path_for(self, file_id: str) -> Optional[Path]:
        record = self.get(file_id)
        if not record:
            return None
        candidate = (self.storage_root / record["storage_path"]).resolve()
        try:
            candidate.relative_to(self.storage_root.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def read(self, file_id: str) -> bytes:
        path = self.path_for(file_id)
        if not path:
            raise FileNotFoundError(file_id)
        return path.read_bytes()

    def delete(self, file_id: str) -> bool:
        record = self.get(file_id)
        if not record:
            return False
        path = self.path_for(file_id)
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM project_files WHERE id = ?",
                (file_id,),
            )
        if path:
            shutil.rmtree(path.parent, ignore_errors=True)
        return cursor.rowcount > 0

    def clear_project(self, project_id: str) -> int:
        records = self.list(project_id)
        removed = 0
        for record in records:
            removed += 1 if self.delete(record["id"]) else 0
        return removed

    def remove_project_storage(self, project_id: str) -> bool:
        """Remove an already de-referenced project directory after DB commit."""
        scope = (project_id or "").strip()
        if not scope or scope == DEFAULT_PROJECT_ID:
            return False
        candidate = (self.storage_root / scope).resolve()
        root = self.storage_root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        if not candidate.exists():
            return False
        shutil.rmtree(candidate, ignore_errors=True)
        return not candidate.exists()


project_file_store = ProjectFileStore()
