"""Tests for SAIMON-PGVECTOR-CODEC-1 — asyncpg pgvector codec registration.

KPI-bound slice: `kpi_id: retrieval.hit_rate` (baseline 0.00 live — the vector
path of `search_knowledge_graph` raised `DatabaseError: expected str, got list`
because asyncpg had no codec for the pgvector `vector` type, and the handler
swallowed the error, dropping to synthetic `kg-N` fallback).

Unit tests cover the codec (encode/decode/register) and pool wiring. The
search-server vector path is verified against a mocked DB pool, and the keyword
fallback is verified when embedding is unavailable.
"""

import sys

from research_shared.db import (
    DatabaseConfig,
    DatabasePool,
    _decode_vector,
    _encode_vector,
    _register_pgvector_codec,
)


class TestVectorEncoding:
    def test_encode_list(self):
        """A list[float] encodes to the pgvector text literal."""
        assert _encode_vector([1.0, 2.5, 3.0]) == "[1.0,2.5,3.0]"

    def test_encode_tuple(self):
        """A tuple encodes the same way as a list."""
        assert _encode_vector((0.0, 1.0)) == "[0.0,1.0]"

    def test_encode_string_passthrough(self):
        """An existing text literal passes through unchanged."""
        assert _encode_vector("[1.0,2.0]") == "[1.0,2.0]"

    def test_encode_empty(self):
        """An empty list encodes to an empty vector literal."""
        assert _encode_vector([]) == "[]"


class TestVectorDecoding:
    def test_decode_text_literal(self):
        """A pgvector text literal decodes to a list[float]."""
        assert _decode_vector("[1.0,2.5,3.0]") == [1.0, 2.5, 3.0]

    def test_decode_empty_literal(self):
        """An empty literal decodes to an empty list."""
        assert _decode_vector("[]") == []

    def test_decode_non_vector_passthrough(self):
        """Non-vector values pass through untouched."""
        assert _decode_vector("not a vector") == "not a vector"
        assert _decode_vector(42) == 42


class _FakeConn:
    """Asyncpg connection double for codec registration tests."""

    def __init__(self, typname=None, nspname=None, fail_query=False):
        self._typname = typname
        self._nspname = nspname
        self._fail_query = fail_query
        self.registered = None

    async def fetchrow(self, query, *args):
        if self._fail_query:
            raise RuntimeError("no vector extension")
        if self._typname is None:
            return None
        return {"typname": self._typname, "nspname": self._nspname}

    async def set_type_codec(self, name, **kwargs):
        self.registered = (name, kwargs)


class TestRegisterPgvectorCodec:
    async def test_registers_codec_when_vector_type_present(self):
        """Codec is registered with the discovered type name + schema."""
        conn = _FakeConn(typname="vector", nspname="public")
        await _register_pgvector_codec(conn)

        assert conn.registered is not None
        name, kwargs = conn.registered
        assert name == "vector"
        assert kwargs["schema"] == "public"
        assert kwargs["format"] == "text"
        assert kwargs["encoder"] is _encode_vector
        assert kwargs["decoder"] is _decode_vector

    async def test_no_op_when_vector_type_missing(self):
        """Without the vector type, no codec is registered."""
        conn = _FakeConn(typname=None, nspname=None)
        await _register_pgvector_codec(conn)
        assert conn.registered is None

    async def test_no_op_when_query_fails(self):
        """A failed lookup leaves the connection untouched."""
        conn = _FakeConn(fail_query=True)
        await _register_pgvector_codec(conn)
        assert conn.registered is None


class TestPoolWiring:
    async def test_get_pool_passes_init_codec(self, mock_db_url_env, monkeypatch):
        """The asyncpg pool is created with the pgvector codec init hook."""
        captured = {}

        class _FakeAsyncpg:
            @staticmethod
            async def create_pool(url, **kwargs):
                captured["url"] = url
                captured["kwargs"] = kwargs
                return object()

        monkeypatch.setitem(sys.modules, "asyncpg", _FakeAsyncpg())

        pool = DatabasePool(DatabaseConfig(database_url="postgresql://u:p@h/db"))
        await pool._get_pool()

        assert captured["kwargs"]["init"] is _register_pgvector_codec


class TestVectorPath:
    async def test_vector_search_returns_real_rows(self, monkeypatch):
        """The vector path returns real KG rows (not synthetic kg-N)."""
        from saimon_mcp.search import server

        rows = [{"id": "node-1", "title": "Real node", "similarity": 0.9}]

        class _Pool:
            async def fetch(self, query, *args):
                return rows

        monkeypatch.setattr(server, "_db_pool", _Pool())
        monkeypatch.setattr(
            "research_shared.embedding.embed_local",
            lambda *a, **k: [0.1] * 768,
        )

        result = await server._vector_search("probe query", 10, None, None, ["reality"])

        assert result is not None
        assert result == rows
        assert result[0]["id"] == "node-1"

    async def test_vector_search_returns_none_when_embedding_unavailable(self, monkeypatch):
        """Fail-closed: no embedding → None so keyword fallback runs."""
        from saimon_mcp.search import server

        monkeypatch.setattr(server, "_db_pool", object())
        monkeypatch.setattr(
            "research_shared.embedding.embed_local",
            lambda *a, **k: None,
        )

        result = await server._vector_search("probe query", 10, None, None, ["reality"])

        assert result is None
