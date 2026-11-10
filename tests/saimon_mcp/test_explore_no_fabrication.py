"""Degraded responses must never invent content (#266 follow-up).

The rule is one line: a fallback may say "I don't know", never "here is an
answer". Synthetic rows are indistinguishable from real ones once they leave the
service — an agent quotes them, a report cites them, and nothing in the payload
says they were made up.

Two real cases motivated this file: `search_knowledge_graph` returned
"Knowledge graph result 0 for: <query>" with fabricated relevance scores, and
`discover_connections` returned a path through a fake `kg-intermediate` node —
a fabricated *relationship* between two real ids.
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

FAKE_ID = "kg-intermediate"


@pytest.fixture
def client(monkeypatch):
    api_key = "test-key"
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.explore.server", None)
    from saimon_mcp.explore.server import app

    return TestClient(app), api_key


def _post(client, api_key, tool, params):
    return client.post(
        f"/tools/{tool}",
        json={"trace_id": "3f6c1a1e-0000-4000-8000-000000000000", "content_type": "probe", "parameters": params},
        headers={"X-Saimon-API-Key": api_key},
    )


class TestExploreDegraded:
    def test_explore_content_returns_no_invented_rows(self, client):
        c, key = client
        body = _post(c, key, "explore_content", {"query": "anything"}).json()
        assert body["data"]["results"] == []
        assert "unavailable" in body["data"]["reason"]

    def test_browse_returns_no_invented_items(self, client):
        c, key = client
        body = _post(c, key, "browse_by_type", {"content_type": "character"}).json()
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_discover_connections_does_not_invent_a_path(self, client):
        c, key = client
        body = _post(
            c, key, "discover_connections",
            {"source_id": "a", "target_id": "b"},
        ).json()
        assert body["data"]["paths"] == []
        assert FAKE_ID not in str(body)
