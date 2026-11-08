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
import re
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

# The canonical fulltext store is the knowledge graph, NOT the api-mcp's
# per-user ``documents`` table.  ``download_fulltext`` → ``persist_fulltext_document``
# writes ``fulltext_document`` + ``fulltext_chunk`` nodes here, and fulltext
# retrieval (search_knowledge_graph) reads from here too.
# See SAIMON-FULLTEXT-DOCUMENTS-1 (#216) for the diagnosis.
FULLTEXT_STORE_TABLE = "knowledge_graph_nodes"

_EMPTY_JSONB_ARRAY = "[]"

# Postgres text/vector columns reject NUL bytes and unpaired surrogates; PDF text
# extraction produces both on malformed fonts and embedded binary streams.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def sanitize_pg_text(value: str | None) -> str | None:
    """Make extracted text safe for a Postgres ``text`` column.

    NUL (0x00) cannot be stored at all; unpaired surrogates cannot be encoded to
    UTF-8. Both abort the whole ingest transaction, so strip them at the single
    persistence choke point rather than trusting every extractor.
    """
    if not isinstance(value, str):
        return value
    return _SURROGATE_RE.sub("", value.replace("\x00", ""))



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


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[,;:])\s+")
_LIST_ITEM_RE = re.compile(r"^(?:\d+[).]|[-*•])\s+")
_LEADER_RE = re.compile(r"\.{4,}")


def _is_low_signal_line(line: str) -> bool:
    """Drop rules, dot leaders, bare numbers and punctuation-only lines."""
    stripped = line.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[\W_]+", stripped) or _LEADER_RE.search(stripped):
        return True
    if re.fullmatch(r"\(?\d+\)?", stripped):
        return True
    alpha = sum(ch.isalpha() for ch in stripped)
    if alpha == 0:
        return True
    punctuation = sum((not ch.isalnum()) and (not ch.isspace()) for ch in stripped)
    return punctuation > alpha * 2 and len(stripped) > 12


def _clean_paragraphs(raw_text: str) -> list[str]:
    """Recover paragraph boundaries from the extracted text.

    Blank lines end a paragraph, a list item starts its own, and a line ending in
    a hyphen continues the previous one (PDF text extraction splits words across
    lines). Low-signal lines are dropped rather than embedded as noise.
    """
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current).strip())
            current.clear()

    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush()
            continue
        if _is_low_signal_line(line):
            flush()
            continue
        if _LIST_ITEM_RE.match(line):
            flush()
            current.append(line)
            continue
        if current and current[-1].endswith("-"):
            current[-1] = f"{current[-1][:-1]}{line}"
            continue
        current.append(line)

    flush()
    return [paragraph for paragraph in paragraphs if paragraph]


def _split_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        chunks.append(current)
        current = word
    chunks.append(current)
    return chunks


def _split_units(paragraph: str, max_chars: int) -> list[str]:
    """Sentences, then clauses, then words — never split a sentence needlessly."""
    sentences = [s.strip() for s in _SENTENCE_BOUNDARY_RE.split(paragraph) if s.strip()]
    if not sentences:
        sentences = [paragraph.strip()]

    units: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            units.append(sentence)
            continue
        clauses = [c.strip() for c in _CLAUSE_BOUNDARY_RE.split(sentence) if c.strip()]
        if len(clauses) > 1:
            for clause in clauses:
                units.extend(
                    [clause] if len(clause) <= max_chars else _split_words(clause, max_chars)
                )
            continue
        units.extend(_split_words(sentence, max_chars))
    return units


def chunk_text(
    text: str,
    min_chars: int = FULLTEXT_CHUNK_MIN,
    max_chars: int = FULLTEXT_CHUNK_MAX,
    overlap: int = FULLTEXT_CHUNK_OVERLAP,
) -> list[str]:
    """Pack *text* into chunks that respect its form.

    Paragraph and sentence boundaries come from the source document; a chunk is
    filled towards *min_chars* and never exceeds *max_chars*, and it only breaks
    a sentence when that sentence alone is longer than a chunk. The last unit of
    a chunk is repeated at the head of the next one when it fits in *overlap*,
    so a fact split across a boundary stays retrievable from both sides.

    Previously this flattened every newline before cutting a fixed window, which
    shredded tables and headings; the form of the source is now the first input.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        cleaned = " ".join(_clean_paragraphs(text))
        return [cleaned] if cleaned else []

    units: list[str] = []
    for paragraph in _clean_paragraphs(text):
        units.extend(_split_units(paragraph, max_chars))
    if not units:
        units = _split_words(" ".join(text.split()), max_chars)

    def overlap_tail(units_in_chunk: list[str]) -> list[str]:
        if overlap <= 0:
            return []
        tail: list[str] = []
        total = 0
        for unit in reversed(units_in_chunk):
            if total + len(unit) + (1 if tail else 0) > overlap:
                break
            tail.insert(0, unit)
            total += len(unit) + (1 if len(tail) > 1 else 0)
        return tail

    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(" ".join(current))
            current = overlap_tail(current)

    for unit in units:
        while len(unit) > max_chars:
            if current:
                flush()
                current = []
            head = unit[:max_chars].rsplit(" ", 1)[0] or unit[:max_chars]
            chunks.append(head)
            unit = unit[len(head) :].strip()
        current_len = len(" ".join(current))
        if current and current_len + 1 + len(unit) > max_chars:
            flush()
            current_len = len(" ".join(current))
        current.append(unit)
        # Fill towards the cap rather than flushing at the floor: a chunk that
        # stops at min_chars throws away context the next sentence would give.
        if len(" ".join(current)) >= max_chars * 0.9:
            flush()

    flush()
    return [c for c in chunks if c]


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
    collection: str = "research",
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Persist one document node + N chunk nodes with ``part_of`` edges.

    Idempotent on DOI: if a ``fulltext_document`` node already exists for the
    DOI, its stale chunks (and their ``part_of`` edges) are replaced rather
    than duplicated.

    ``embeddings`` is aligned with ``chunks``; a None entry stores a NULL
    embedding (fail-closed when the local model is unavailable).
    """
    document_metadata = {
        "doi": doi,
        "source_index": source_index,
        "content_hash": content_hash_value,
        "s3_key": s3_key,
        "fetched_at": fetched_at,
    }

    existing_id = await db.fetchval(
        f"SELECT id FROM {FULLTEXT_STORE_TABLE} "
        "WHERE content_type = $1 AND metadata->>'doi' = $2 "
        "ORDER BY created_at LIMIT 1",
        CONTENT_TYPE_FULLTEXT_DOCUMENT,
        doi,
    )
    document_node_id = str(existing_id) if existing_id else str(uuid.uuid4())
    # A document and its chunks are one content unit (#244): same collection,
    # same unit_id. Callers that do not supply a unit_id get the document node
    # id, so chunks are always linkable to their parent unit.
    unit_id = unit_id or document_node_id

    if existing_id:
        # Refresh: drop stale chunks + their part_of edges, then update the doc.
        await db.execute(
            "DELETE FROM knowledge_graph_edges WHERE source_id IN "
            f"(SELECT id FROM {FULLTEXT_STORE_TABLE} "
            " WHERE content_type = $1 AND metadata->>'doi' = $2)",
            CONTENT_TYPE_FULLTEXT_CHUNK,
            doi,
        )
        await db.execute(
            f"DELETE FROM {FULLTEXT_STORE_TABLE} "
            "WHERE content_type = $1 AND metadata->>'doi' = $2",
            CONTENT_TYPE_FULLTEXT_CHUNK,
            doi,
        )
        await db.execute(
            "UPDATE knowledge_graph_nodes "
            "SET title = $1, body = $2, metadata = $3, collection = $4, "
            "unit_id = $5, updated_at = now() "
            "WHERE id = $6",
            sanitize_pg_text(title),
            sanitize_pg_text(abstract or ""),
            json.dumps(document_metadata),
            collection,
            unit_id,
            document_node_id,
        )
    else:
        await db.execute(
            "INSERT INTO knowledge_graph_nodes "
            "(id, title, content_type, body, metadata, collection, unit_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            document_node_id,
            sanitize_pg_text(title),
            CONTENT_TYPE_FULLTEXT_DOCUMENT,
            sanitize_pg_text(abstract or ""),
            json.dumps(document_metadata),
            collection,
            unit_id,
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
            f"INSERT INTO {FULLTEXT_STORE_TABLE} "
            "(id, title, content_type, body, metadata, embedding, collection, unit_id) "
            "VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8)",
            chunk_id,
            sanitize_pg_text(f"{title} — chunk {index + 1}"),
            CONTENT_TYPE_FULLTEXT_CHUNK,
            sanitize_pg_text(chunk),
            json.dumps(chunk_metadata),
            vector,
            collection,
            unit_id,
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
