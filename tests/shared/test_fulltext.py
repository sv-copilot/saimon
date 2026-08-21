"""Tests for research_shared.fulltext — extraction, chunking, and persistence.

SAIMON-FULLTEXT-RAG-1 (#97).
"""

from __future__ import annotations

import hashlib
import sys
import types

from research_shared.fulltext import (
    FULLTEXT_CHUNK_MAX,
    chunk_text,
    content_hash,
    extract_text,
    persist_fulltext_document,
    register_fulltext_content_types,
)

# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_sha256_hex(self) -> None:
        assert content_hash(b"hello") == hashlib.sha256(b"hello").hexdigest()

    def test_deterministic(self) -> None:
        assert content_hash(b"data") == content_hash(b"data")


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_txt(self) -> None:
        assert extract_text(b"plain text here", "txt") == "plain text here"

    def test_html(self) -> None:
        html = b"<html><body><p>Hello</p><p>World</p></body></html>"
        text = extract_text(html, "html")
        assert "Hello" in text
        assert "World" in text

    def test_empty_bytes_returns_none(self) -> None:
        assert extract_text(b"", "pdf") is None

    def test_pdf_via_mocked_pypdf(self, monkeypatch) -> None:
        fake_pypdf = types.ModuleType("pypdf")

        class _FakePage:
            def extract_text(self) -> str:
                return "Extracted PDF text."

        class _FakeReader:
            def __init__(self, stream) -> None:
                self.pages = [_FakePage()]

        fake_pypdf.PdfReader = _FakeReader
        monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
        assert "Extracted PDF text." in extract_text(b"%PDF-1.4 fake", "pdf")

    def test_unknown_type_falls_back_to_plain(self) -> None:
        assert extract_text(b"raw text", "djvu") == "raw text"


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self) -> None:
        assert chunk_text("short") == ["short"]

    def test_empty_text_no_chunks(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_long_text_multiple_chunks_within_cap(self) -> None:
        text = ("word " * 2000)  # 10000 chars
        chunks = chunk_text(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= FULLTEXT_CHUNK_MAX

    def test_chunks_preserve_start_and_end(self) -> None:
        text = " ".join(f"token{i:05d}" for i in range(500))
        chunks = chunk_text(text)
        assert chunks[0].startswith("token00000")
        assert chunks[-1].endswith("token00499")


# ---------------------------------------------------------------------------
# persistence (mock DB)
# ---------------------------------------------------------------------------


class _RecordingDb:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple] = []

    async def execute(self, query: str, *args):
        self.statements.append(query)
        self.args.append(args)
        return "OK"

    async def fetchrow(self, query: str, *args):
        return None

    async def fetchval(self, query: str, *args):
        return None


class TestPersistence:
    async def test_register_content_types(self) -> None:
        db = _RecordingDb()
        await register_fulltext_content_types(db)
        assert len(db.statements) == 2
        assert "content_type_registry" in db.statements[0]

    async def test_persist_fulltext_document(self) -> None:
        db = _RecordingDb()
        result = await persist_fulltext_document(
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
        assert result["chunk_count"] == 2
        assert len(result["chunk_node_ids"]) == 2
        # 1 doc node + 2 chunk nodes + 2 edges = 5 statements
        assert len(db.statements) == 5
        all_args = [arg for args in db.args for arg in args]
        assert "fulltext_document" in all_args
        assert "fulltext_chunk" in all_args
        assert any("part_of" in s for s in db.statements)
