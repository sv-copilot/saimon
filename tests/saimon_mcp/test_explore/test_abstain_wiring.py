"""Wiring test for the explore retrieval gate (SAIMON-RETRIEVAL-ABSTAIN-1 #234).

The rerank unit gate is covered in test_search/test_abstain.py.  This file
pins the WIRING: explore_content must route its rows through the shared
reranker, return no rows when the gate fires, and expose relevance_score and
no_strong_evidence in the payload.

Embeddings are stubbed so the test asserts the gate, not the model.
"""

from __future__ import annotations

import pytest


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return list(self._rows)


def _rows():
    return [
        {
            "id": "n1",
            "title": "Tufte data ink ratio",
            "content_type": "research_note",
            "body": "Tufte data ink ratio chart design",
            "relevance": 0.5,
        },
        {
            "id": "n2",
            "title": "Budget variance worksheet",
            "content_type": "research_note",
            "body": "budget variance worksheet landscaping crew",
            "relevance": 0.5,
        },
    ]


@pytest.fixture
def wired(client, monkeypatch):
    """Point explore at a fake pool and a deterministic embedding backend."""
    import saimon_mcp.explore.server as server

    monkeypatch.setattr(server, "_db_pool", _FakePool(_rows()), raising=False)

    def embed(text: str):
        if "tufte" in text.lower() or "data ink" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]

    monkeypatch.setattr(server, "_rerank_embed_fn", lambda: embed, raising=False)
    return server


def _explore(client, auth_headers, query, trace_id):
    return client.post(
        "/tools/explore_content",
        json={
            "trace_id": trace_id,
            "content_type": "explore",
            "parameters": {"query": query},
        },
        headers=auth_headers,
    )


class TestExploreGate:
    def test_nonsense_query_returns_nothing(self, client, auth_headers, wired, sample_trace_id):
        response = _explore(client, auth_headers, "xzqv plorbinate frobnication", sample_trace_id)
        data = response.json()["data"]

        assert data["results"] == []
        assert data["total"] == 0
        assert data["no_strong_evidence"] is True

    def test_real_query_keeps_the_head_and_exposes_score(
        self, client, auth_headers, wired, sample_trace_id
    ):
        response = _explore(client, auth_headers, "Tufte data ink ratio", sample_trace_id)
        data = response.json()["data"]

        assert data["no_strong_evidence"] is False
        assert data["results"]
        assert data["results"][0]["id"] == "n1"
        assert "relevance_score" in data["results"][0]
