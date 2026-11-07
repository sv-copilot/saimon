"""Postgres-safe text: NUL bytes and lone surrogates must never reach the driver.

PDF text extraction emits 0x00 on malformed font maps and embedded binary
streams. Postgres rejects 0x00 in a text column with
``invalid byte sequence for encoding "UTF8": 0x00`` and aborts the whole ingest
transaction (observed live on arXiv PDFs, 2026-11-07).
"""

from __future__ import annotations

import asyncio

from research_shared.fulltext import persist_fulltext_document, sanitize_pg_text


class _FakeDB:
    def __init__(self):
        self.statements: list[tuple[str, tuple]] = []

    async def fetchval(self, query, *args):
        return None

    async def execute(self, query, *args):
        self.statements.append((query, args))
        return "OK"


class TestSanitizePgText:
    def test_strips_nul_bytes(self):
        assert sanitize_pg_text("a\x00b\x00\x00c") == "abc"

    def test_strips_lone_surrogates(self):
        assert sanitize_pg_text("ok\ud800bad\udfff") == "okbad"

    def test_keeps_newlines_tabs_and_unicode(self):
        text = "line one\nline two\ttabbed — em dash ✓"
        assert sanitize_pg_text(text) == text

    def test_non_str_passthrough(self):
        assert sanitize_pg_text(None) is None


class TestPersistSanitizes:
    def test_no_statement_argument_carries_nul_or_surrogate(self):
        db = _FakeDB()
        asyncio.run(
            persist_fulltext_document(
                db,
                doi="url:https://example.org/nul.pdf",
                title="Title\x00 with nul",
                source_index="url_import",
                abstract="abstract\x00text",
                s3_key="https://example.org/nul.pdf",
                content_hash_value="h",
                fetched_at="2026-11-07T00:00:00+00:00",
                chunks=["chunk\x00one", "chunk\ud800two"],
                embeddings=[None, None],
            )
        )
        assert db.statements, "persist wrote nothing"
        for query, args in db.statements:
            for arg in args:
                if isinstance(arg, str):
                    assert "\x00" not in arg
                    assert "\ud800" not in arg and "\udfff" not in arg
        titles = [a for q, a in db.statements if "INSERT INTO knowledge_graph_nodes" in q]
        assert titles, "expected insert statements"
