"""Tests for local nomic-embed-text embedding (SAIMON-EMBEDDING-LOCAL-1).

Covers the local fastembed backend (768-dim, fail-closed), the schema
migration (VECTOR(768) + HNSW index), and the pgvector similarity search path.
All network-free: fastembed is mocked, never instantiated.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeEmbeddingModel:
    def __init__(self, *args, dims: int = 768, **kwargs):
        self._dims = dims

    def embed(self, documents):
        return [[0.1] * self._dims for _ in documents]


class _UnavailableEmbeddingModel:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("model not available")


def _install_fake_fastembed(monkeypatch: pytest.MonkeyPatch, model_cls) -> None:
    fake = SimpleNamespace(TextEmbedding=model_cls)
    monkeypatch.setitem(sys.modules, "fastembed", fake)


class TestLocalEmbedding:
    def test_embed_local_returns_768_dim_vector(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_shared.embedding import embed_local, reset_embedding_cache

        reset_embedding_cache()
        _install_fake_fastembed(monkeypatch, _FakeEmbeddingModel)
        result = embed_local("hello world")
        assert result is not None
        assert len(result) == 768
        assert all(isinstance(value, float) for value in result)

    def test_embed_local_returns_none_when_model_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_shared.embedding import embed_local, reset_embedding_cache

        reset_embedding_cache()
        _install_fake_fastembed(monkeypatch, _UnavailableEmbeddingModel)
        assert embed_local("hello") is None

    def test_embed_local_returns_none_without_fastembed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_shared.embedding import embed_local, reset_embedding_cache

        reset_embedding_cache()
        monkeypatch.setitem(sys.modules, "fastembed", None)
        assert embed_local("hello") is None

    def test_generate_embedding_uses_local_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.generate.server import _generate_embedding
        from research_shared.embedding import reset_embedding_cache

        reset_embedding_cache()
        monkeypatch.setenv("SAIMON_EMBEDDING_BACKEND", "local")
        _install_fake_fastembed(monkeypatch, _FakeEmbeddingModel)
        result = asyncio.run(_generate_embedding("hello"))
        assert result is not None
        assert len(result) == 768


class TestSchemaMigration:
    def test_schema_declares_vector_768(self) -> None:
        schema = (REPO_ROOT / "schema.sql").read_text(encoding="utf-8")
        assert "VECTOR(768)" in schema

    def test_schema_declares_hnsw_index_on_embedding(self) -> None:
        schema = (REPO_ROOT / "schema.sql").read_text(encoding="utf-8")
        assert "hnsw" in schema.lower()
        assert "embedding" in schema.lower()


class TestVectorSearch:
    def test_vector_search_returns_ranked_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.search import server as search_server
        from research_shared.embedding import reset_embedding_cache

        reset_embedding_cache()
        _install_fake_fastembed(monkeypatch, _FakeEmbeddingModel)

        rows = [
            {
                "id": "kg-1",
                "title": "Ranked one",
                "content_type": "note",
                "relevance": 0.9,
                "similarity": 0.95,
            },
            {
                "id": "kg-2",
                "title": "Ranked two",
                "content_type": "note",
                "relevance": 0.7,
                "similarity": 0.8,
            },
        ]
        fake_pool = MagicMock()
        fake_pool.fetch = AsyncMock(return_value=rows)
        monkeypatch.setattr(search_server, "_db_pool", fake_pool)

        results = asyncio.run(search_server._vector_search("nearest docs", 5, None))
        assert results == rows
        # The similarity query must use the pgvector cosine operator.
        sql = fake_pool.fetch.call_args[0][0]
        assert "<=>" in sql

    def test_vector_search_returns_none_without_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.search import server as search_server
        from research_shared.embedding import reset_embedding_cache

        reset_embedding_cache()
        monkeypatch.setitem(sys.modules, "fastembed", None)
        assert asyncio.run(search_server._vector_search("x", 5, None)) is None
