"""Tests for the download_fulltext dedup-gap fix (SAIMON-FULLTEXT-DEDUP-FIX-1, #194).

The bug: ``store_shadow_fulltext`` wrote the S3 cache row (``full_text_path``)
before chunk/embed/persist, so a run that failed after the S3 upload left a
cache row with no KG nodes. Every re-run then short-circuited to
``cache_hit: True, chunk_count: 0`` and silently never ingested.

These tests pin the fix:
1. A fresh DOI fully ingests and marks the cache row ``ingested_at``.
2. A re-run after a SUCCESS short-circuits (``cache_hit``) without duplicating.
3. A cache row with ``full_text_path`` but ``ingested_at IS NULL`` RE-INGESTS.
4. ``persist_fulltext_document`` is idempotent on DOI.
"""

from __future__ import annotations

import pytest

from research_shared.adapters.base import FulltextFetchResult
from research_shared.fulltext import persist_fulltext_document
from saimon_mcp.search.server import _download_fulltext_flow


class FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        self.uploaded[key] = data
        return key


class FakeAdapter:
    name = "internet_archive"

    def __init__(self) -> None:
        self.calls = 0
        self.result = FulltextFetchResult(
            source_index="internet_archive",
            doi="10.1000/dedup",
            data=b"the quick brown fox jumps over the lazy dog. " * 200,
            file_type="txt",
        )

    async def fetch_fulltext(self, result):
        self.calls += 1
        return self.result


class FakeDB:
    """Records statements; serves cache/meta rows and an optional existing doc id."""

    def __init__(self, cache_row: dict | None = None, existing_doc_id: str | None = None) -> None:
        self.cache_row = cache_row
        self.existing_doc_id = existing_doc_id
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "full_text_path" in query:
            return dict(self.cache_row) if self.cache_row is not None else None
        return None

    async def fetchval(self, query: str, *args):
        return self.existing_doc_id


def _embed(text: str):
    return [0.1] * 768


async def _run(db: FakeDB, **kwargs) -> dict:
    storage = kwargs.pop("storage", FakeStorage())
    adapter = kwargs.pop("adapter", FakeAdapter())

    def get_adapter(name: str):
        return adapter if name == adapter.name else None

    defaults = {
        "doi": "10.1000/dedup",
        "source": {"source_index": "internet_archive", "title": "Dedup Paper", "doi": "10.1000/dedup"},
        "fetch_only": False,
        "embed_fn": _embed,
    }
    defaults.update(kwargs)
    return await _download_fulltext_flow(db, storage, get_adapter, **defaults)


@pytest.fixture(autouse=True)
def _reset_schema_guard():
    from research_shared.s3_storage import reset_ingested_column_guard

    reset_ingested_column_guard()
    yield
    reset_ingested_column_guard()


class TestDedupFix:
    async def test_fresh_doi_ingests_and_marks_ingested(self) -> None:
        db = FakeDB(cache_row=None)
        adapter = FakeAdapter()
        result = await _run(db, adapter=adapter)

        assert result["ok"] is True
        assert result["cache_hit"] is False
        assert result["document_node_id"]
        assert result["chunk_count"] >= 1
        assert adapter.calls == 1
        # the cache row is marked ingested only after persist succeeds
        assert any(
            "UPDATE shadow_sources_cache SET ingested_at" in q for q, _ in db.executed
        )

    async def test_rerun_after_success_is_cache_hit(self) -> None:
        db = FakeDB(cache_row={
            "full_text_path": "fulltext/abc/1.txt",
            "file_type": "txt",
            "title": "Dedup Paper",
            "source_index": "internet_archive",
            "ingested_at": "2026-08-21T00:00:00+00:00",
        })
        adapter = FakeAdapter()
        result = await _run(db, adapter=adapter)

        assert result["ok"] is True
        assert result["cache_hit"] is True
        assert result["s3_key"] == "fulltext/abc/1.txt"
        assert adapter.calls == 0

    async def test_incomplete_ingestion_reingests(self) -> None:
        # The bug: full_text_path present but ingested_at IS NULL -> must re-ingest.
        db = FakeDB(cache_row={
            "full_text_path": "fulltext/abc/1.txt",
            "file_type": "txt",
            "title": "Dedup Paper",
            "source_index": "internet_archive",
            "ingested_at": None,
        })
        adapter = FakeAdapter()
        result = await _run(db, adapter=adapter)

        assert result["ok"] is True
        assert result["cache_hit"] is False
        assert result["document_node_id"]
        assert result["chunk_count"] >= 1
        assert adapter.calls == 1


class TestPersistIdempotent:
    async def test_persist_fulltext_document_is_idempotent_on_doi(self) -> None:
        db = FakeDB(existing_doc_id="11111111-1111-1111-1111-111111111111")
        result = await persist_fulltext_document(
            db,
            doi="10.1000/dedup",
            title="Dedup Paper",
            source_index="internet_archive",
            abstract="abstract",
            s3_key="fulltext/abc/1.txt",
            content_hash_value="hash",
            fetched_at="2026-08-21T00:00:00+00:00",
            chunks=["chunk one", "chunk two"],
            embeddings=[[0.1, 0.2], None],
        )
        assert result["chunk_count"] == 2
        assert result["document_node_id"] == "11111111-1111-1111-1111-111111111111"
        # stale chunks for this DOI are deleted before the refresh insert
        assert any(
            "DELETE FROM knowledge_graph_edges" in q for q, _ in db.executed
        )
        assert any(
            "DELETE FROM knowledge_graph_nodes" in q for q, _ in db.executed
        )
        assert any(
            "UPDATE knowledge_graph_nodes" in q for q, _ in db.executed
        )
        # no new document node INSERT on the refresh path (chunks are re-inserted)
        assert not any(
            "fulltext_document" in args for _, args in db.executed
        )
