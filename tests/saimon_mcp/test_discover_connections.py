"""discover_connections must find real paths and never invent one (#266 follow-up).

The fallback used to return a path through a fabricated `kg-intermediate` node,
which hid a live bug: the query selected `relationship_type` from a table whose
column is `relation_type`, so every call failed and every answer was invented.
"""

from __future__ import annotations

import sys
from typing import Any

from fastapi.testclient import TestClient

from research_shared.db import DatabaseError

API_KEY = "test-key"
TRACE = "3f6c1a1e-0000-4000-8000-000000000001"


class _Pool:
    def __init__(self, direct: list[dict[str, Any]], hops: list[dict[str, Any]]):
        self._direct = direct
        self._hops = hops
        self.queries: list[str] = []

    async def fetch(self, sql, *params):
        self.queries.append(sql)
        return self._direct if "JOIN" not in sql else self._hops


class _Broken:
    async def fetch(self, *a, **k):
        raise DatabaseError("database down")


def _call(monkeypatch, pool, params=None):
    monkeypatch.setenv("SAIMON_API_KEY", API_KEY)
    sys.modules.pop("saimon_mcp.explore.server", None)
    from saimon_mcp.explore import server

    monkeypatch.setattr(server, "_db_pool", pool, raising=False)
    client = TestClient(server.app)
    return client.post(
        "/tools/discover_connections",
        json={
            "trace_id": TRACE,
            "content_type": "probe",
            "parameters": params or {"source_id": "a", "target_id": "b"},
        },
        headers={"X-Saimon-API-Key": API_KEY},
    ).json()


def test_query_uses_the_real_column_name(monkeypatch):
    pool = _Pool([{"from_id": "a", "to_id": "b", "type": "references"}], [])
    _call(monkeypatch, pool)
    assert "relation_type" in pool.queries[0]
    assert "relationship_type" not in pool.queries[0]


def test_direct_edge_is_a_path(monkeypatch):
    pool = _Pool([{"from_id": "a", "to_id": "b", "type": "references"}], [])
    body = _call(monkeypatch, pool)["data"]
    assert len(body["paths"]) == 1
    assert body["paths"][0]["length"] == 1


def test_one_hop_is_found_when_there_is_no_direct_edge(monkeypatch):
    hops = [{
        "start_id": "a", "middle_id": "m", "first_type": "references",
        "end_id": "b", "second_type": "extends",
    }]
    body = _call(monkeypatch, _Pool([], hops))["data"]
    assert body["paths"][0]["length"] == 2
    assert body["paths"][0]["nodes"] == ["a", "m", "b"]


def test_no_path_is_empty_not_degraded(monkeypatch):
    """A reachable graph with no path is an answer, not an outage."""
    body = _call(monkeypatch, _Pool([], []))
    assert body["data"]["paths"] == []
    assert body["status"] == "success"


def test_unreachable_graph_returns_nothing(monkeypatch):
    body = _call(monkeypatch, _Broken())
    assert body["data"]["paths"] == []
    assert body["status"] == "degraded"
    assert "kg-intermediate" not in str(body)
