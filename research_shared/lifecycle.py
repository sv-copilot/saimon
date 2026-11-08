"""Document ingest lifecycle (SAIMON-DOC-LIFECYCLE-1).

A half-ingested document must never look like a good one. Status lives in
``knowledge_graph_nodes.metadata`` rather than a new column: ``schema.sql`` is
mounted only into a fresh database, so a column would not exist on the live
cluster when the code that reads it deploys — the query would fail, not degrade.

States: uploaded → parsing → chunking → embedding → ready, or failed (+ reason).
"""

from __future__ import annotations

import json
from typing import Any

STATUS_KEY = "status"
ERROR_KEY = "error_message"

STATUS_READY = "ready"
STATUS_PARSING = "parsing"
STATUS_CHUNKING = "chunking"
STATUS_EMBEDDING = "embedding"
STATUS_FAILED = "failed"

ALL_STATUSES = (STATUS_PARSING, STATUS_CHUNKING, STATUS_EMBEDDING, STATUS_READY, STATUS_FAILED)

DOCUMENT_CONTENT_TYPE = "fulltext_document"


async def ensure_document_stub(
    db: Any, *, doi: str, title: str, source_index: str = "url_import"
) -> str:
    """Create (or find) the document row before any work starts.

    Returns the document node id. The row exists so a failure has somewhere to be
    recorded — the NUL-byte ingest failures of 2026-11-07 left no trace at all.
    """
    existing = await db.fetchval(
        "SELECT id FROM knowledge_graph_nodes "
        "WHERE content_type = $1 AND metadata->>'doi' = $2 LIMIT 1",
        DOCUMENT_CONTENT_TYPE,
        doi,
    )
    if existing:
        await set_document_status(db, doi=doi, status=STATUS_PARSING)
        return str(existing)

    import uuid

    node_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO knowledge_graph_nodes "
        "(id, title, content_type, body, metadata) VALUES ($1, $2, $3, $4, $5)",
        node_id,
        title or doi,
        DOCUMENT_CONTENT_TYPE,
        "",
        json.dumps({"doi": doi, "source_index": source_index, STATUS_KEY: STATUS_PARSING}),
    )
    return node_id


async def set_document_status(
    db: Any, *, doi: str, status: str, error: str | None = None
) -> None:
    """Advance a document's status. Never raises for an unknown doi."""
    if status not in ALL_STATUSES:
        raise ValueError(f"unknown document status: {status}")
    patch: dict[str, Any] = {STATUS_KEY: status}
    if error is not None:
        patch[ERROR_KEY] = error
    await db.execute(
        "UPDATE knowledge_graph_nodes "
        "SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb, updated_at = now() "
        "WHERE content_type = $2 AND metadata->>'doi' = $3",
        json.dumps(patch),
        DOCUMENT_CONTENT_TYPE,
        doi,
    )


async def mark_failed(db: Any, *, doi: str, error: str) -> None:
    await set_document_status(db, doi=doi, status=STATUS_FAILED, error=error)
