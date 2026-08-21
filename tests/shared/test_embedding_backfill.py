"""Tests for the embedding backfill + node-embed guard (SAIMON-EMBEDDING-BACKFILL-1, #195).

The 17 pre-embedding-era ``research_note`` nodes have ``embedding IS NULL``,
so they are invisible to vector retrieval. These tests pin:
1. ``embed_node_text`` produces a 768-dim vector (fail-closed via ``embed_local``).
2. The backfill embeds NULL-embedding nodes.
3. The backfill is idempotent (re-runs skip already-embedded nodes).
4. A newly created node with NULL embedding is caught by the sweep.
5. An embed failure on one node does not abort the batch.
"""

from __future__ import annotations

import pytest

from research_shared.embedding import backfill_null_embeddings, embed_node_text


def _vector(n: int = 768) -> list[float]:
    return [0.1] * n


class FakePool:
    """Records fetch/execute; serves a fixed list of NULL-embedding rows."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.fetched_queries: list[str] = []
        self.updates: list[tuple[str, dict]] = []

    async def fetch(self, query: str, *args):
        self.fetched_queries.append(query)
        return list(self.rows)

    async def execute(self, query: str, *args):
        self.updates.append((query, args))
        return "OK"


class TestEmbedNodeText:
    def test_embeds_title_plus_body_via_embed_local(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_embed_local(text: str, model_name: str, dimensions: int):
            captured["text"] = text
            captured["model"] = model_name
            captured["dims"] = dimensions
            return _vector()

        monkeypatch.setattr("research_shared.embedding.embed_local", fake_embed_local)
        vector = embed_node_text("My Note", "Some body text")

        assert vector is not None
        assert len(vector) == 768
        assert "My Note" in captured["text"]
        assert "Some body text" in captured["text"]

    def test_empty_title_and_body_returns_none(self) -> None:
        assert embed_node_text("", "") is None


class TestBackfill:
    async def test_embeds_null_embedding_nodes(self) -> None:
        pool = FakePool(rows=[
            {"id": "n1", "title": "Note 1", "body": "body one"},
            {"id": "n2", "title": "Note 2", "body": "body two"},
        ])
        result = await backfill_null_embeddings(pool, embed_fn=lambda t, b: _vector())

        assert result == {"embedded": 2, "failed": 0}
        assert any("embedding IS NULL" in q for q in pool.fetched_queries)
        assert len(pool.updates) == 2
        for query, args in pool.updates:
            assert "UPDATE knowledge_graph_nodes" in query
            assert args[1] in ("n1", "n2")

    async def test_is_idempotent_skips_already_embedded(self) -> None:
        # A re-run selects only NULL-embedding rows; none remain.
        pool = FakePool(rows=[])
        result = await backfill_null_embeddings(pool, embed_fn=lambda t, b: _vector())

        assert result == {"embedded": 0, "failed": 0}
        assert any("embedding IS NULL" in q for q in pool.fetched_queries)
        assert pool.updates == []

    async def test_sweeps_newly_created_node(self) -> None:
        # A node created without an embedding is caught by the sweep.
        pool = FakePool(rows=[
            {"id": "new-node", "title": "Fresh Note", "body": "no embedding yet"},
        ])
        result = await backfill_null_embeddings(pool, embed_fn=lambda t, b: _vector())

        assert result == {"embedded": 1, "failed": 0}
        assert len(pool.updates) == 1
        assert pool.updates[0][1][1] == "new-node"

    async def test_embed_failure_does_not_abort_batch(self) -> None:
        pool = FakePool(rows=[
            {"id": "good", "title": "Good", "body": "ok"},
            {"id": "bad", "title": "Bad", "body": "fails"},
            {"id": "good2", "title": "Good2", "body": "ok2"},
        ])

        def flaky_embed(title: str, body: str):
            if body == "fails":
                return None
            return _vector()

        result = await backfill_null_embeddings(pool, embed_fn=flaky_embed)

        assert result == {"embedded": 2, "failed": 1}
        assert len(pool.updates) == 2
        updated_ids = {args[1] for _, args in pool.updates}
        assert updated_ids == {"good", "good2"}
