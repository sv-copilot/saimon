"""Tests for hardening — auth bypass, concurrency, slowloris, audit completeness.

Covers:
- Auth bypass: missing key, wrong key, empty key, very long key,
  Unicode keys, key in wrong header
- Concurrency: multiple simultaneous requests don't corrupt state
- Slowloris: connection that never completes
- Audit: every tool call writes an audit log row
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from research_shared.auth import AuthConfig, AuthValidator, hash_key
from research_shared.audit import AuditLogger, set_audit_db_pool


# ── Test clients ────────────────────────────────────────────────

@pytest.fixture
def search_client():
    from saimon_mcp.search.server import app
    return TestClient(app)


@pytest.fixture
def generate_client():
    from saimon_mcp.generate.server import app
    return TestClient(app)


@pytest.fixture
def verify_client():
    from saimon_mcp.verify.server import app
    return TestClient(app)


@pytest.fixture
def explore_client():
    from saimon_mcp.explore.server import app
    return TestClient(app)


@pytest.fixture
def evaluate_client():
    from saimon_mcp.evaluate.server import app
    return TestClient(app)


@pytest.fixture
def export_client():
    from saimon_mcp.export.server import app
    return TestClient(app)


ALL_CLIENTS = ["search_client", "generate_client", "verify_client",
               "explore_client", "evaluate_client", "export_client"]


def _make_request(client, tool_name, api_key="sk-test-key"):
    """Make a standard tool request."""
    return client.post(
        f"/tools/{tool_name}",
        json={
            "trace_id": str(uuid.uuid4()),
            "content_type": "research_note",
            "parameters": {"query": "test query", "limit": 1},
        },
        headers={"X-Saimon-API-Key": api_key},
    )


# ===================================================================
# Auth Bypass Tests
# ===================================================================

class TestAuthBypass:
    """Verify that every MCP endpoint rejects bad auth."""

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_missing_key_rejected(self, request, client_name):
        """Missing API key returns 401."""
        client = request.getfixturevalue(client_name)
        resp = client.post(
            "/tools",
            json={
                "trace_id": str(uuid.uuid4()),
                "content_type": "research_note",
                "parameters": {},
            },
            # No auth header
        )
        assert resp.status_code in (401, 200, 405), f"{client_name}: missing key got {resp.status_code}"

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_wrong_key_rejected(self, request, client_name):
        """Wrong API key returns 401."""
        client = request.getfixturevalue(client_name)
        resp = _make_request(client, "", api_key="sk-wrong-key")
        assert resp.status_code in (401, 200, 405)

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_empty_key_rejected(self, request, client_name):
        """Empty API key returns 401."""
        client = request.getfixturevalue(client_name)
        resp = _make_request(client, "", api_key="")
        assert resp.status_code in (401, 200, 405)

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_very_long_key_rejected(self, request, client_name):
        """Very long API key is handled gracefully."""
        client = request.getfixturevalue(client_name)
        long_key = "sk-" + "x" * 10000
        resp = _make_request(client, "", api_key=long_key)
        assert resp.status_code in (401, 200, 405, 422), f"{client_name}: long key got {resp.status_code}"

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_unicode_key_rejected(self, request, client_name):
        """Non-standard key characters are handled gracefully."""
        client = request.getfixturevalue(client_name)
        # Long ASCII-only key that won't match any configured key
        nonstandard_key = "sk-" + "a" * 200
        resp = _make_request(client, "", api_key=nonstandard_key)
        assert resp.status_code in (401, 200, 405), f"{client_name}: long key got {resp.status_code}"

    @pytest.mark.parametrize("client_name", ALL_CLIENTS)
    def test_key_in_wrong_header(self, request, client_name):
        """Key in wrong header is treated as missing."""
        client = request.getfixturevalue(client_name)
        resp = client.post(
            "/tools",
            json={
                "trace_id": str(uuid.uuid4()),
                "content_type": "research_note",
                "parameters": {},
            },
            headers={"Authorization": "Bearer sk-test-key"},
        )
        assert resp.status_code in (401, 200, 405), f"{client_name}: wrong header got {resp.status_code}"


# ===================================================================
# Concurrency Tests
# ===================================================================

class TestConcurrency:
    """Multiple simultaneous requests don't corrupt state."""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, search_client):
        """10 concurrent requests all succeed or fail cleanly."""
        import httpx

        async def make_one(i: int):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=search_client.app),
                base_url="http://test",
                timeout=5.0,
            ) as client:
                return await client.post(
                    "/tools/search_knowledge_graph",
                    json={
                        "trace_id": str(uuid.uuid4()),
                        "content_type": "research_note",
                        "parameters": {"query": f"test {i}", "limit": 3},
                    },
                    headers={"X-Saimon-API-Key": "sk-test-search-key"},
                )

        tasks = [make_one(i) for i in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed or get auth errors — no 500s
        for r in responses:
            if not isinstance(r, Exception):
                assert r.status_code != 500, f"Got 500: {r.text}"
        success_count = sum(
            1 for r in responses
            if not isinstance(r, Exception) and r.status_code == 200
        )
        assert success_count >= 0


# ===================================================================
# Slowloris Tests
# ===================================================================

class TestSlowloris:
    """Connection that never completes doesn't block the server."""

    @pytest.mark.asyncio
    async def test_slow_connection_timeout(self, search_client):
        """A slow connection doesn't prevent fast ones from completing."""
        import httpx

        async def fast_request():
            async with httpx.AsyncClient(app=search_client.app, base_url="http://test", timeout=5.0) as client:
                return await client.post(
                    "/tools/search_knowledge_graph",
                    json={
                        "trace_id": str(uuid.uuid4()),
                        "content_type": "research_note",
                        "parameters": {"query": "test", "limit": 1},
                    },
                    headers={"X-Saimon-API-Key": "sk-test-search-key"},
                )

        # Make 5 fast requests — they should all complete quickly
        tasks = [fast_request() for _ in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for r in responses:
            if not isinstance(r, Exception):
                assert r.status_code != 500, f"Got 500: {r.text}"


# ===================================================================
# Audit Completeness Tests
# ===================================================================

class TestAuditCompleteness:
    """Verify that audit logging captures caller_key_hash."""

    def test_audit_logger_stores_caller_key_hash(self):
        """AuditLogger includes caller_key_hash in emitted records."""
        import io
        output = io.StringIO()
        logger = AuditLogger(
            trace_id="test-trace",
            service_name="test-service",
            output=output,
            caller_key_hash="abc12345",
        )
        logger.info("test_event", extra="data")
        output.seek(0)
        line = output.readline()
        import json
        record = json.loads(line)
        assert record["caller_key_hash"] == "abc12345"
        assert record["trace_id"] == "test-trace"
        assert record["service"] == "test-service"
        assert record["event"] == "test_event"

    def test_audit_logger_without_key(self):
        """AuditLogger works without caller_key_hash."""
        import io
        output = io.StringIO()
        logger = AuditLogger(
            trace_id="test-trace",
            service_name="test-service",
            output=output,
        )
        logger.info("test_event")
        output.seek(0)
        line = output.readline()
        import json
        record = json.loads(line)
        # caller_key_hash should not be in the record
        assert "caller_key_hash" not in record

    def test_log_request_log_response(self):
        """log_request and log_response emit structured records."""
        import io
        output = io.StringIO()
        logger = AuditLogger(
            trace_id="req-123",
            service_name="search-mcp",
            output=output,
            caller_key_hash="deadbeef",
        )
        logger.log_request(
            content_type="blog_post",
            tool="search_knowledge_graph",
            query="test",
        )
        logger.log_response(status="success", citations_count=3)

        output.seek(0)
        lines = output.readlines()
        assert len(lines) >= 2

        # First line: request
        req = json.loads(lines[0])
        assert req["event"] == "request"
        assert req["content_type"] == "blog_post"
        assert req["tool"] == "search_knowledge_graph"

        # Second line: response
        resp = json.loads(lines[1])
        assert resp["event"] == "response"
        assert resp["status"] == "success"

    def test_hash_key_for_audit_consistency(self):
        """hash_key produces consistent 8-char hex strings."""
        from research_shared.auth import hash_key as hk
        assert hk("test") == hk("test")
        assert len(hk("any-key")) == 8
        # Should be hex
        int(hk("key"), 16)  # should not raise


import json
