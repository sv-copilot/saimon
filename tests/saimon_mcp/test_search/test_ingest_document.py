"""Tests for ingest_document (#248) and the collection/unit_id wiring.

Network is never used: URL validation is exercised against real refusal cases
and a monkeypatched resolver, and persistence is exercised against a fake DB
that records the statements it is given.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from research_shared.fulltext import persist_fulltext_document
from saimon_mcp.search.server import _ingest_url_error


class _FakeDB:
    def __init__(self, existing_id=None):
        self.statements: list[tuple[str, tuple]] = []
        self._existing_id = existing_id

    async def fetchval(self, query, *args):
        return self._existing_id

    async def execute(self, query, *args):
        self.statements.append((query, args))
        return "OK"


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/paper.pdf",
            "file:///etc/passwd",
            "http://localhost/paper.pdf",
            "http://127.0.0.1/paper.pdf",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.5/paper.pdf",
        ],
    )
    def test_refuses_non_public_targets(self, url):
        assert _ingest_url_error(url) is not None

    def test_allows_a_public_host(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda host, port, *a, **k: [(2, 1, 6, "", ("151.101.1.1", 0))],
        )
        assert _ingest_url_error("https://arxiv.org/pdf/2005.11401") is None

    def test_blocks_a_hostname_that_resolves_private(self, monkeypatch):
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda host, port, *a, **k: [(2, 1, 6, "", ("192.168.1.10", 0))],
        )
        assert _ingest_url_error("https://internal.example/paper.pdf") is not None


class TestPersistenceCarriesTheUnit:
    def test_document_and_chunks_share_collection_and_unit(self):
        db = _FakeDB()
        out = asyncio.run(
            persist_fulltext_document(
                db,
                doi="url:https://example.org/paper.pdf",
                title="A Paper",
                source_index="url_import",
                abstract="abstract",
                s3_key="https://example.org/paper.pdf",
                content_hash_value="abc123",
                fetched_at="2026-11-07T00:00:00+00:00",
                chunks=["chunk one", "chunk two"],
                embeddings=[None, None],
                collection="pdfs",
            )
        )

        assert out["chunk_count"] == 2
        doc_insert = next(q for q, _ in db.statements if "INSERT INTO knowledge_graph_nodes" in q)
        assert "collection" in doc_insert and "unit_id" in doc_insert

        chunk_inserts = [
            (q, a) for q, a in db.statements if "INSERT INTO knowledge_graph_nodes" in q
        ][1:]
        assert len(chunk_inserts) == 2
        for query, args in chunk_inserts:
            assert "collection" in query and "unit_id" in query
            assert args[6] == "pdfs"
            assert args[7] == out["document_node_id"]

    def test_unit_id_defaults_to_the_document_node(self):
        db = _FakeDB()
        out = asyncio.run(
            persist_fulltext_document(
                db,
                doi="url:https://example.org/b.pdf",
                title="B",
                source_index="url_import",
                abstract=None,
                s3_key="https://example.org/b.pdf",
                content_hash_value="h",
                fetched_at="2026-11-07T00:00:00+00:00",
                chunks=["only chunk"],
                embeddings=[None],
            )
        )
        chunk_args = [a for q, a in db.statements if "INSERT INTO knowledge_graph_nodes" in q][1]
        assert chunk_args[7] == out["document_node_id"]
        assert chunk_args[6] == "research"

    def test_chunk_metadata_records_the_unit_link(self):
        db = _FakeDB()
        asyncio.run(
            persist_fulltext_document(
                db,
                doi="url:https://example.org/c.pdf",
                title="C",
                source_index="url_import",
                abstract=None,
                s3_key="https://example.org/c.pdf",
                content_hash_value="h",
                fetched_at="2026-11-07T00:00:00+00:00",
                chunks=["c1"],
                embeddings=[None],
            )
        )
        chunk_args = [a for q, a in db.statements if "INSERT INTO knowledge_graph_nodes" in q][1]
        meta = json.loads(chunk_args[4])
        assert meta["part_of"]
        assert meta["source_index"] == "url_import"
