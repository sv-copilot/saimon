"""Document lifecycle (SAIMON-DOC-LIFECYCLE-1).

Status lives in metadata, not a column: schema.sql only runs on a fresh database,
so a new column would be absent on the live cluster when the reading code
deploys. These tests pin the transitions and the failure record.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from research_shared.lifecycle import (
    STATUS_CHUNKING,
    STATUS_FAILED,
    STATUS_PARSING,
    STATUS_READY,
    ensure_document_stub,
    mark_failed,
    set_document_status,
)


class _FakeDB:
    def __init__(self, existing_id: str | None = None):
        self.statements: list[tuple[str, tuple]] = []
        self._existing = existing_id

    async def fetchval(self, query, *args):
        return self._existing

    async def execute(self, query, *args):
        self.statements.append((query, args))
        return "OK"


class TestStub:
    def test_creates_a_row_with_parsing_status(self):
        db = _FakeDB()
        node_id = asyncio.run(
            ensure_document_stub(db, doi="url:https://example.org/a.pdf", title="A")
        )
        assert node_id
        insert = next(q for q, _ in db.statements if "INSERT INTO knowledge_graph_nodes" in q)
        args = next(a for q, a in db.statements if "INSERT INTO knowledge_graph_nodes" in q)
        assert args[0] == node_id
        assert args[1] == "A"
        meta = json.loads(args[4])
        assert meta["status"] == STATUS_PARSING
        assert meta["doi"] == "url:https://example.org/a.pdf"
        assert insert

    def test_existing_row_is_reused_and_marked_parsing(self):
        db = _FakeDB(existing_id="11111111-1111-1111-1111-111111111111")
        node_id = asyncio.run(
            ensure_document_stub(db, doi="url:https://example.org/b.pdf", title="B")
        )
        assert node_id == "11111111-1111-1111-1111-111111111111"
        assert not any("INSERT INTO knowledge_graph_nodes" in q for q, _ in db.statements)
        update = next(a for q, a in db.statements if "UPDATE knowledge_graph_nodes" in q)
        assert json.loads(update[0])["status"] == STATUS_PARSING


class TestTransitions:
    def test_status_is_written_to_metadata(self):
        db = _FakeDB()
        asyncio.run(set_document_status(db, doi="url:x", status=STATUS_CHUNKING))
        patch = json.loads(next(a for q, a in db.statements if "UPDATE" in q)[0])
        assert patch == {"status": STATUS_CHUNKING}

    def test_failure_records_a_reason(self):
        db = _FakeDB()
        asyncio.run(mark_failed(db, doi="url:x", error="nul byte"))
        patch = json.loads(next(a for q, a in db.statements if "UPDATE" in q)[0])
        assert patch["status"] == STATUS_FAILED
        assert patch["error_message"] == "nul byte"

    def test_unknown_status_is_rejected(self):
        db = _FakeDB()
        with pytest.raises(ValueError):
            asyncio.run(set_document_status(db, doi="url:x", status="banana"))

    def test_ready_is_a_terminal_write(self):
        db = _FakeDB()
        asyncio.run(set_document_status(db, doi="url:x", status=STATUS_READY))
        patch = json.loads(next(a for q, a in db.statements if "UPDATE" in q)[0])
        assert patch["status"] == STATUS_READY


class TestRetrievalFilter:
    def test_both_queries_select_document_status(self):
        import inspect

        from saimon_mcp.search import server

        for fn in (server._vector_search, server._keyword_search):
            assert "COALESCE(metadata->>'status', 'ready') as doc_status" in inspect.getsource(fn)

    def test_failed_documents_are_filtered_unless_allowed(self):
        import inspect

        from saimon_mcp.search import server

        src = inspect.getsource(server._retrieve_and_rerank)
        assert 'c.get("doc_status") or "ready"' in src
        assert "allow_failed" in src
