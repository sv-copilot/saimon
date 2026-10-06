"""Tests for the low-quality fulltext purge (SAIMON-OCR-CLEANUP-1, #198).

The bug: #196 (quality gate) stops *new* garbled OCR from being ingested, but
the garbled German-Copperfield ``fulltext_chunk`` nodes ingested *before* #196
remain — along with their document node, cache row, and S3 key — and keep
polluting the vector index.

These tests pin the purge:
1. Only garbled chunks (failing the #196 quality scorer) are removed.
2. A document with remaining clean chunks is left intact.
3. The purge is idempotent — a second run is a no-op.
"""

from __future__ import annotations

from research_shared.fulltext_purge import purge_low_quality_fulltext

from research_shared.sources import fulltext_cache_table

FULLTEXT_CACHE_TABLE = fulltext_cache_table()

GARBLED_BODY = "\ufffd" * 300 + "\x00" * 300 + "x" * 500
CLEAN_BODY = (
    "The quick brown fox jumps over the lazy dog and then it runs away "
    "across the field under the bright morning sun to find a quiet place. " * 20
)


class FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_bytes(self, key: str) -> bool:
        self.deleted.append(key)
        return True


class FakeDB:
    """Stateful fake: serves chunk/doc rows and applies deletions to itself."""

    def __init__(
        self,
        chunks: list[dict],
        docs: list[dict],
        cache: dict[str, str] | None = None,
    ) -> None:
        self.chunks = chunks
        self.docs = docs
        self.cache = cache or {}
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        if "DELETE FROM knowledge_graph_nodes" in query:
            node_id = args[0]
            self.chunks = [c for c in self.chunks if c["id"] != node_id]
            self.docs = [d for d in self.docs if d["id"] != node_id]
        elif f"DELETE FROM {FULLTEXT_CACHE_TABLE}" in query:
            self.cache.pop(args[0], None)
        return "OK"

    async def fetch(self, query: str, *args):
        if "content_type = $1" in query:
            return list(self.chunks)
        return []

    async def fetchrow(self, query: str, *args):
        if f"{FULLTEXT_CACHE_TABLE}" in query:
            doi = args[0]
            path = self.cache.get(doi)
            return {"full_text_path": path} if path is not None else None
        if "content_type = $1 AND metadata->>'doi' = $2" in query:
            doi = args[1]
            for doc in self.docs:
                if doc["metadata"]["doi"] == doi:
                    return doc
            return None
        return None

    async def fetchval(self, query: str, *args):
        if "count(*)" in query:
            doi = args[1]
            return sum(1 for c in self.chunks if c["metadata"]["doi"] == doi)
        return None


def _chunk(cid: str, doi: str, body: str) -> dict:
    return {
        "id": cid,
        "body": body,
        "metadata": {"doi": doi, "part_of": f"doc-{doi}"},
    }


def _doc(did: str, doi: str, s3_key: str) -> dict:
    return {"id": did, "metadata": {"doi": doi, "s3_key": s3_key}}


class TestPurgeLowQualityFulltext:
    async def test_removes_only_garbled_chunks_and_orphaned_doc(self) -> None:
        db = FakeDB(
            chunks=[
                _chunk("chunk-garbled", "10.1000/garbled", GARBLED_BODY),
                _chunk("chunk-clean", "10.1000/clean", CLEAN_BODY),
            ],
            docs=[
                _doc("doc-garbled", "10.1000/garbled", "fulltext/garbled/1.txt"),
                _doc("doc-clean", "10.1000/clean", "fulltext/clean/1.txt"),
            ],
            cache={
                "10.1000/garbled": "fulltext/garbled/1.txt",
                "10.1000/clean": "fulltext/clean/1.txt",
            },
        )
        storage = FakeStorage()

        summary = await purge_low_quality_fulltext(db, storage)

        assert summary["garbled_chunks_found"] == 1
        assert summary["chunks_deleted"] == 1
        assert summary["documents_deleted"] == 1
        assert summary["cache_rows_deleted"] == 1
        assert summary["s3_keys_deleted"] == 1
        # garbled chunk + its orphaned doc removed; clean chunk/doc untouched
        assert [c["id"] for c in db.chunks] == ["chunk-clean"]
        assert [d["id"] for d in db.docs] == ["doc-clean"]
        assert "fulltext/garbled/1.txt" in storage.deleted
        assert "fulltext/clean/1.txt" not in storage.deleted

    async def test_document_with_remaining_clean_chunks_is_kept(self) -> None:
        db = FakeDB(
            chunks=[
                _chunk("chunk-garbled", "10.1000/mixed", GARBLED_BODY),
                _chunk("chunk-clean", "10.1000/mixed", CLEAN_BODY),
            ],
            docs=[_doc("doc-mixed", "10.1000/mixed", "fulltext/mixed/1.txt")],
            cache={"10.1000/mixed": "fulltext/mixed/1.txt"},
        )
        storage = FakeStorage()

        summary = await purge_low_quality_fulltext(db, storage)

        assert summary["garbled_chunks_found"] == 1
        assert summary["chunks_deleted"] == 1
        assert summary["documents_deleted"] == 0
        assert summary["cache_rows_deleted"] == 0
        assert summary["s3_keys_deleted"] == 0
        assert [c["id"] for c in db.chunks] == ["chunk-clean"]
        assert [d["id"] for d in db.docs] == ["doc-mixed"]
        assert storage.deleted == []

    async def test_purge_is_idempotent(self) -> None:
        db = FakeDB(
            chunks=[_chunk("chunk-garbled", "10.1000/garbled", GARBLED_BODY)],
            docs=[_doc("doc-garbled", "10.1000/garbled", "fulltext/garbled/1.txt")],
            cache={"10.1000/garbled": "fulltext/garbled/1.txt"},
        )
        storage = FakeStorage()

        first = await purge_low_quality_fulltext(db, storage)
        assert first["garbled_chunks_found"] == 1
        assert first["chunks_deleted"] == 1

        second = await purge_low_quality_fulltext(db, storage)
        assert second["garbled_chunks_found"] == 0
        assert second["chunks_deleted"] == 0
        assert second["documents_deleted"] == 0
        assert second["cache_rows_deleted"] == 0
        assert second["s3_keys_deleted"] == 0
        assert len(storage.deleted) == 1  # only the first run deleted anything
