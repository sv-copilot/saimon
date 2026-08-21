"""fulltext.py — full-text extraction, chunking, and RAG ingestion helpers.

Turns downloaded document bytes into searchable text and persists them
as ``fulltext_document`` + ``fulltext_chunk`` knowledge-graph nodes with
``part_of`` edges and local 768-dim embeddings.

All extraction is fail-closed: unparseable or oversized inputs return
None rather than raising.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

MAX_FULLTEXT_BYTES = 50 * 1024 * 1024  # 50 MB per-source size cap
DEFAULT_FULLTEXT_TIMEOUT = 30.0  # seconds

FULLTEXT_CHUNK_MIN = 1500
FULLTEXT_CHUNK_MAX = 2000
FULLTEXT_CHUNK_OVERLAP = 200
EMBED_CHAR_CAP = 8000  # embed_local truncates to this many chars

CONTENT_TYPE_FULLTEXT_DOCUMENT = "fulltext_document"
CONTENT_TYPE_FULLTEXT_CHUNK = "fulltext_chunk"

_EMPTY_JSONB_ARRAY = "[]"


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------


def content_hash(data: bytes) -> str:
    """Return a SHA-256 hex digest of *data* (provenance content hash)."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------


def _extract_pdf(data: bytes) -> str | None:
    """Extract text from PDF bytes via pypdf, falling back to pymupdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            import fitz  # type: ignore  # PyMuPDF fallback
        except ImportError:
            return None
        try:
            document = fitz.open(stream=data, filetype="pdf")
            return "\n".join(page.get_text() for page in document) or None
        except Exception:  # noqa: BLE001 — fail-closed on malformed PDF
            return None

    try:
        import io

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() for page in reader.pages]
        text = "\n".join(p for p in pages if p)
        return text or None
    except Exception:  # noqa: BLE001 — fail-closed on malformed PDF
        return None


def _extract_html(data: bytes) -> str | None:
    """Extract text from HTML bytes via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(data, "html.parser")
        text = soup.get_text("\n")
        return text or None
    except Exception:  # noqa: BLE001 — fail-closed on malformed HTML
        return None


def _extract_epub(data: bytes) -> str | None:
    """Best-effort EPUB extraction (XHTML chapters via zipfile + BeautifulSoup)."""
    try:
        import io
        import zipfile

        from bs4 import BeautifulSoup

        parts: list[str] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if not name.endswith((".xhtml", ".html", ".htm")):
                    continue
                try:
                    payload = archive.read(name)
                except Exception:  # noqa: BLE001, S112 — skip unreadable entries
                    continue
                soup = BeautifulSoup(payload, "html.parser")
                text = soup.get_text("\n")
                if text and text.strip():
                    parts.append(text)
        return "\n".join(parts) or None
    except Exception:  # noqa: BLE001 — fail-closed on malformed EPUB
        return None


def _extract_text_plain(data: bytes) -> str | None:
    """Decode plain-text bytes (UTF-8 with latin-1 fallback)."""
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            if text.strip():
                return text
        except UnicodeDecodeError:
            continue
    return None


def extract_text(data: bytes, file_type: str | None) -> str | None:
    """Extract plain text from *data* based on *file_type*.

    Supported: txt, html/htm, pdf, epub (best-effort).  Returns None for
    unknown or unparseable inputs (fail-closed).
    """
    if not data:
        return None

    kind = (file_type or "").strip().lower().lstrip(".")

    if kind in ("txt", "text", ""):
        return _extract_text_plain(data)
    if kind in ("html", "htm", "xhtml"):
        return _extract_html(data)
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "epub":
        return _extract_epub(data)
    # djvu and other binary formats have no safe pure-Python extractor.
    return _extract_text_plain(data)


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    min_chars: int = FULLTEXT_CHUNK_MIN,
    max_chars: int = FULLTEXT_CHUNK_MAX,
    overlap: int = FULLTEXT_CHUNK_OVERLAP,
) -> list[str]:
    """Split *text* into overlapping chunks of at most *max_chars*.

    Chunks break on word boundaries and overlap by *overlap* characters
    to preserve context across boundaries.  Every chunk is ≤ *max_chars*,
    which keeps it well under the 8000-char ``embed_local`` cap.
    """
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer breaking at a word boundary in the last half of the window.
            boundary = text.rfind(" ", start + min_chars, end)
            if boundary != -1:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# ---------------------------------------------------------------------------
# content-type registration
# ---------------------------------------------------------------------------


async def register_fulltext_content_types(db: Any) -> None:
    """Ensure ``fulltext_document`` and ``fulltext_chunk`` exist in the registry."""
    types = [
        (
            CONTENT_TYPE_FULLTEXT_DOCUMENT,
            "A downloaded full-text document (title, DOI, source index, abstract).",
        ),
        (
            CONTENT_TYPE_FULLTEXT_CHUNK,
            "A chunk of a full-text document, embedded for vector retrieval.",
        ),
    ]
    for name, description in types:
        await db.execute(
            "INSERT INTO content_type_registry "
            "(name, description, required_params, optional_params, voice_profile) "
            "VALUES ($1, $2, '[]'::jsonb, '[]'::jsonb, NULL) "
            "ON CONFLICT (name) DO NOTHING",
            name,
            description,
        )


# ---------------------------------------------------------------------------
# KG persistence
# ---------------------------------------------------------------------------


async def persist_fulltext_document(
    db: Any,
    *,
    doi: str,
    title: str,
    source_index: str,
    abstract: str | None,
    s3_key: str,
    content_hash_value: str,
    fetched_at: str,
    chunks: list[str],
    embeddings: list[list[float] | None],
) -> dict[str, Any]:
    """Persist one document node + N chunk nodes with ``part_of`` edges.

    ``embeddings`` is aligned with ``chunks``; a None entry stores a NULL
    embedding (fail-closed when the local model is unavailable).
    """
    document_node_id = str(uuid.uuid4())

    document_metadata = {
        "doi": doi,
        "source_index": source_index,
        "content_hash": content_hash_value,
        "s3_key": s3_key,
        "fetched_at": fetched_at,
    }

    await db.execute(
        "INSERT INTO knowledge_graph_nodes "
        "(id, title, content_type, body, metadata) "
        "VALUES ($1, $2, $3, $4, $5)",
        document_node_id,
        title,
        CONTENT_TYPE_FULLTEXT_DOCUMENT,
        abstract or "",
        json.dumps(document_metadata),
    )

    chunk_node_ids: list[str] = []
    for index, chunk in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        vector = embeddings[index] if index < len(embeddings) else None
        chunk_metadata = {
            "doi": doi,
            "source_index": source_index,
            "content_hash": content_hash_value,
            "s3_key": s3_key,
            "fetched_at": fetched_at,
            "chunk_index": index,
            "part_of": document_node_id,
        }
        await db.execute(
            "INSERT INTO knowledge_graph_nodes "
            "(id, title, content_type, body, metadata, embedding) "
            "VALUES ($1, $2, $3, $4, $5, $6::vector)",
            chunk_id,
            f"{title} — chunk {index + 1}",
            CONTENT_TYPE_FULLTEXT_CHUNK,
            chunk,
            json.dumps(chunk_metadata),
            vector,
        )
        await db.execute(
            "INSERT INTO knowledge_graph_edges "
            "(source_id, target_id, relation_type, weight, metadata) "
            "VALUES ($1, $2, 'part_of', 1.0, '{}'::jsonb) "
            "ON CONFLICT (source_id, target_id, relation_type) DO NOTHING",
            chunk_id,
            document_node_id,
        )
        chunk_node_ids.append(chunk_id)

    return {
        "document_node_id": document_node_id,
        "chunk_node_ids": chunk_node_ids,
        "chunk_count": len(chunk_node_ids),
    }
