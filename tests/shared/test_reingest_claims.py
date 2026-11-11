"""Re-ingest must not orphan the claims it invalidates (#265 follow-up).

A document refresh deletes its chunk rows. Claims are keyed to a chunk by
`metadata->>'source_chunk_id'`, not by an edge, so deleting only edges left them
pointing at ids that no longer existed. Live count when this was written: 219
orphaned claims, and a refreshed paper appeared to have produced nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from research_shared.fulltext import persist_fulltext_document


class _DB:
    """Records statements; returns an existing document id for the lookup."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchval(self, sql: str, *args):
        self.statements.append((sql, args))
        return "doc-existing"

    async def execute(self, sql: str, *args) -> str:
        self.statements.append((sql, args))
        return "OK"


def _run(db: _DB) -> None:
    asyncio.run(
        persist_fulltext_document(
            db,
            doi="arxiv:2404.16130",
            title="t",
            source_index="arxiv",
            abstract="a",
            s3_key="https://example.org/x.pdf",
            content_hash_value="hash",
            fetched_at="2026-11-10T00:00:00Z",
            chunks=["one"],
            embeddings=[[0.0] * 3],
        )
    )


def test_refresh_deletes_claims_derived_from_the_removed_chunks():
    db = _DB()
    _run(db)
    sql = "\n".join(s for s, _ in db.statements)
    assert "DELETE FROM knowledge_graph_nodes WHERE content_type = 'claim'" in sql
    claim_delete = next(
        (args for s, args in db.statements if "content_type = 'claim'" in s), None
    )
    assert claim_delete is not None
    assert "arxiv:2404.16130" in claim_delete


def test_refresh_still_replaces_chunks():
    db = _DB()
    _run(db)
    sql = "\n".join(s for s, _ in db.statements)
    assert "DELETE FROM knowledge_graph_edges" in sql
