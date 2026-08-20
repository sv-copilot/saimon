import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp.explore.gap_sweep import list_gaps, saimon_list_gaps, TOOL_SPEC, GAP_SEVERITIES


class FakeConnection:
    """Minimal fake connection that returns canned results based on the SQL text."""

    def __init__(self, fetch_records=None, fetchval_results=None):
        """
        fetch_records: dict mapping a SQL substring to a list of rows (for `fetch`).
        fetchval_results: dict mapping a SQL substring to a scalar (for `fetchval`).
        """
        self.fetch_records = fetch_records or {}
        self.fetchval_results = fetchval_results or {}

    async def fetch(self, query, *args):
        for key, rows in self.fetch_records.items():
            if key in query:
                return rows
        return []

    async def fetchval(self, query, *args):
        for key, value in self.fetchval_results.items():
            if key in query:
                return value
        # Default to 0
        return 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection):
        self._conn = connection

    def acquire(self):
        return self._conn


@pytest.mark.asyncio
async def test_empty_kg_returns_empty_list():
    """Empty KG should produce gaps: [] — not an error."""
    conn = FakeConnection()
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    assert gaps == []


@pytest.mark.asyncio
async def test_content_type_sparse_gap():
    conn = FakeConnection(
        fetch_records={
            "FROM content_type_registry": [{"type_name": "article", "node_count": 0}]
        }
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    assert len(gaps) == 1
    assert gaps[0]["type"] == "content_type_sparse"
    assert gaps[0]["severity"] == "low"
    assert gaps[0]["count"] == 1


@pytest.mark.asyncio
async def test_observation_unverified_gap():
    conn = FakeConnection(
        fetchval_results={
            "verification_status = 'unverified'": 3,
        }
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    unverified = [g for g in gaps if g["type"] == "observation_unverified"]
    assert len(unverified) == 1
    assert unverified[0]["severity"] == "medium"
    assert unverified[0]["count"] == 3


@pytest.mark.asyncio
async def test_observation_low_confidence_gap():
    conn = FakeConnection(
        fetchval_results={
            "confidence_0_1 < 0.6": 5,
        }
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    low = [g for g in gaps if g["type"] == "observation_low_confidence"]
    assert len(low) == 1
    assert low[0]["severity"] == "medium"
    assert low[0]["count"] == 5


@pytest.mark.asyncio
async def test_search_empty_gap():
    conn = FakeConnection(
        fetchval_results={
            "shadow_search_log": 7,
        }
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    search = [g for g in gaps if g["type"] == "search_empty"]
    assert len(search) == 1
    assert search[0]["severity"] == "high"
    assert search[0]["count"] == 7


@pytest.mark.asyncio
async def test_node_unverified_gap():
    conn = FakeConnection(
        fetchval_results={
            "LEFT JOIN observations o": 4,
        }
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    node = [g for g in gaps if g["type"] == "node_unverified"]
    assert len(node) == 1
    assert node[0]["severity"] == "medium"
    assert node[0]["count"] == 4


@pytest.mark.asyncio
async def test_all_gap_types_present():
    conn = FakeConnection(
        fetch_records={
            "FROM content_type_registry": [
                {"type_name": "a", "node_count": 0},
                {"type_name": "b", "node_count": 1},
            ]
        },
        fetchval_results={
            "verification_status = 'unverified'": 2,
            "confidence_0_1 < 0.6": 3,
            "shadow_search_log": 6,
            "LEFT JOIN observations o": 8,
        },
    )
    pool = FakePool(conn)
    gaps = await list_gaps(pool)
    gap_types = {g["type"] for g in gaps}
    assert gap_types == set(GAP_SEVERITIES.keys())
    counts = {g["type"]: g["count"] for g in gaps}
    assert counts["content_type_sparse"] == 2
    assert counts["observation_unverified"] == 2
    assert counts["observation_low_confidence"] == 3
    assert counts["search_empty"] == 6
    assert counts["node_unverified"] == 8


@pytest.mark.asyncio
async def test_mcp_tool_handler_and_spec():
    # Tool handler delegates to list_gaps
    conn = FakeConnection(
        fetchval_results={"confidence_0_1 < 0.6": 1}
    )
    pool = FakePool(conn)
    result = await saimon_list_gaps(pool)
    assert isinstance(result, list)
    assert TOOL_SPEC["name"] == "saimon_list_gaps"
    assert callable(TOOL_SPEC["handler"])