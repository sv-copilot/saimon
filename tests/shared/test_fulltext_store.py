"""Tests locking in the fulltext-store diagnosis (SAIMON-FULLTEXT-DOCUMENTS-1, #216).

Prod postgres showed ``documents`` = 0 rows while ``knowledge_graph_nodes``
(161), ``observations`` (511), and ``shadow_sources_cache`` (3) were populated.

Diagnosis: ``documents`` is NOT the fulltext store.  It is the api-mcp's
per-user document table (SAIMON-DOCUMENTS-1), created at runtime by
``saimon_mcp.api.server._ensure_documents_table``.  Fulltext lives in
``knowledge_graph_nodes`` as ``fulltext_document`` + ``fulltext_chunk`` nodes,
and fulltext ingestion/retrieval already point at that live store.

These tests lock in the invariant so no reader can silently point fulltext
ingestion (or retrieval) at the empty ``documents`` table again.
"""

from __future__ import annotations

from pathlib import Path

from research_shared.fulltext import (
    CONTENT_TYPE_FULLTEXT_CHUNK,
    CONTENT_TYPE_FULLTEXT_DOCUMENT,
    FULLTEXT_STORE_TABLE,
    persist_fulltext_document,
)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema.sql"


class _RecordingDb:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple] = []

    async def execute(self, query: str, *args):
        self.statements.append(query)
        self.args.append(args)
        return "OK"

    async def fetchval(self, query: str, *args):
        return None


class TestFulltextStoreConstant:
    def test_fulltext_store_table_is_knowledge_graph_nodes(self) -> None:
        assert FULLTEXT_STORE_TABLE == "knowledge_graph_nodes"

    def test_content_types_are_fulltext_document_and_chunk(self) -> None:
        assert CONTENT_TYPE_FULLTEXT_DOCUMENT == "fulltext_document"
        assert CONTENT_TYPE_FULLTEXT_CHUNK == "fulltext_chunk"


class TestFulltextPersistenceTargetsLiveStore:
    async def test_persist_writes_to_knowledge_graph_nodes_not_documents(self) -> None:
        db = _RecordingDb()
        await persist_fulltext_document(
            db,
            doi="10.1000/x",
            title="Example",
            source_index="internet_archive",
            abstract="abstract",
            s3_key="fulltext/abc/1.pdf",
            content_hash_value="hash",
            fetched_at="2026-08-21T00:00:00+00:00",
            chunks=["chunk one", "chunk two"],
            embeddings=[[0.1, 0.2], None],
        )
        assert db.statements, "persist_fulltext_document should emit SQL statements"
        # Every node statement targets the live KG store; no statement ever
        # touches the api-mcp's per-user ``documents`` table.
        assert any("knowledge_graph_nodes" in s for s in db.statements)
        for statement in db.statements:
            assert "documents" not in statement, statement


class TestCanonicalSchemaHasNoDocumentsTable:
    def test_schema_sql_defines_no_documents_table(self) -> None:
        """The canonical schema stores fulltext in ``knowledge_graph_nodes``.

        A ``documents`` table would imply fulltext lives outside the KG; the
        api-mcp's per-user ``documents`` table is created at runtime, not in
        ``schema.sql``.
        """
        sql = _SCHEMA_PATH.read_text()
        assert "knowledge_graph_nodes" in sql
        # Guard against a future ``documents`` table sneaking into the
        # canonical fulltext schema.
        assert "CREATE TABLE IF NOT EXISTS documents" not in sql
        assert "CREATE TABLE documents" not in sql
