"""fulltext_purge.py — idempotent cleanup of low-quality full-text nodes.

SAIMON-OCR-CLEANUP-1 (#198): the #196 quality gate stops *new* garbled OCR
from being ingested, but garbled ``fulltext_chunk`` nodes ingested *before*
#196 remain — along with their document node, cache row, and S3 key — and
keep polluting the vector index.

This module identifies ``fulltext_chunk`` nodes whose ``body`` fails the
``research_shared.text_quality`` gate and deletes them plus any orphaned
``fulltext_document`` nodes, full-text cache rows, and S3 objects.
The operation is keyed on the #196 quality scorer (garbled text, not language
identity) and is re-runnable: a second run finds nothing and is a no-op.
"""

from __future__ import annotations

import json
from typing import Any

from research_shared.sources import fulltext_cache_table
from research_shared.text_quality import text_quality_ok

CONTENT_TYPE_FULLTEXT_DOCUMENT = "fulltext_document"
CONTENT_TYPE_FULLTEXT_CHUNK = "fulltext_chunk"


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Return a row's ``metadata`` JSONB as a dict (handles str/dict forms)."""
    raw = row.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_doi(doi: str | None) -> str:
    """Canonical DOI form matching the full-text cache's ``doi``."""
    return (doi or "").strip().lower()


async def find_garbled_chunks(db: Any) -> list[dict[str, Any]]:
    """Return fulltext_chunk rows whose body fails the #196 quality gate."""
    rows = await db.fetch(
        "SELECT id, body, metadata FROM knowledge_graph_nodes "
        "WHERE content_type = $1",
        CONTENT_TYPE_FULLTEXT_CHUNK,
    )
    return [row for row in rows if not text_quality_ok(row.get("body") or "")]


async def purge_low_quality_fulltext(
    db: Any,
    storage: Any = None,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete low-quality fulltext chunks + orphaned documents/cache/S3.

    ``storage`` is an optional ``S3Storage``-like object with a
    ``configured`` flag and a ``delete_bytes(key) -> bool`` method.  When it
    is None or unconfigured, S3 deletion is skipped but everything else still
    runs.

    Returns a summary dict of counts.  Re-running after a successful purge is
    a no-op (all counts zero).
    """
    garbled = await find_garbled_chunks(db)
    summary: dict[str, int] = {
        "garbled_chunks_found": len(garbled),
        "chunks_deleted": 0,
        "documents_deleted": 0,
        "cache_rows_deleted": 0,
        "s3_keys_deleted": 0,
        "dry_run": int(dry_run),
    }
    if not garbled:
        return summary

    affected_dois = {
        _metadata(row).get("doi")
        for row in garbled
        if _metadata(row).get("doi")
    }

    if dry_run:
        summary["chunks_deleted"] = len(garbled)
        return summary

    for row in garbled:
        # ``knowledge_graph_edges`` cascade-deletes the chunk's part_of edges.
        await db.execute(
            "DELETE FROM knowledge_graph_nodes WHERE id = $1", row["id"]
        )
    summary["chunks_deleted"] = len(garbled)

    storage_configured = storage is not None and getattr(storage, "configured", False)

    for doi in sorted(affected_dois):
        remaining = await db.fetchval(
            "SELECT count(*) FROM knowledge_graph_nodes "
            "WHERE content_type = $1 AND metadata->>'doi' = $2",
            CONTENT_TYPE_FULLTEXT_CHUNK,
            doi,
        )
        if remaining:
            continue

        document = await db.fetchrow(
            "SELECT id, metadata FROM knowledge_graph_nodes "
            "WHERE content_type = $1 AND metadata->>'doi' = $2 "
            "ORDER BY created_at LIMIT 1",
            CONTENT_TYPE_FULLTEXT_DOCUMENT,
            doi,
        )
        s3_key: str | None = None
        if document:
            s3_key = _metadata(document).get("s3_key")
            await db.execute(
                "DELETE FROM knowledge_graph_nodes WHERE id = $1", document["id"]
            )
            summary["documents_deleted"] += 1

        cache_row = await db.fetchrow(
            f"SELECT full_text_path FROM {fulltext_cache_table()} WHERE doi = $1",
            _normalize_doi(doi),
        )
        if cache_row is not None:
            s3_key = s3_key or cache_row.get("full_text_path")
            await db.execute(
                f"DELETE FROM {fulltext_cache_table()} WHERE doi = $1",
                _normalize_doi(doi),
            )
            summary["cache_rows_deleted"] += 1

        if s3_key and storage_configured and storage.delete_bytes(s3_key):
            summary["s3_keys_deleted"] += 1

    return summary
