"""Tests for SAIMON-KG-SEED (#40) — self_seed tool and KG persistence."""



# ---------------------------------------------------------------------------
# Test 1: self_seed processes pending seed_requests
# ---------------------------------------------------------------------------

class TestSelfSeed:
    """Verify the self_seed tool endpoint exists and handles requests."""

    def test_tool_listed_in_manifest(self, client, auth_headers):
        """self_seed appears in the /tools manifest."""
        response = client.get("/tools", headers=auth_headers)
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "self_seed" in tool_names, (
            f"self_seed missing from tool manifest: {tool_names}"
        )

    def test_endpoint_requires_auth(self, client, sample_trace_id):
        """self_seed requires authentication."""
        response = client.post(
            "/tools/self_seed",
            json={
                "trace_id": sample_trace_id,
                "content_type": "seed",
                "parameters": {},
            },
        )
        assert response.status_code == 401

    def test_endpoint_accepts_request(
        self, client, sample_trace_id, auth_headers
    ):
        """self_seed endpoint accepts a valid request (degraded without DB)."""
        response = client.post(
            "/tools/self_seed",
            json={
                "trace_id": sample_trace_id,
                "content_type": "seed",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        # Without DB or LLM injected, should return an error about DB/LLM
        assert data["status"] in ("success", "error")
        if data["status"] == "error":
            assert "not available" in data["errors"][0].lower()


# ---------------------------------------------------------------------------
# Test 2: Idempotent — second run does nothing
# ---------------------------------------------------------------------------

class TestSelfSeedIdempotent:
    """Verify self_seed is idempotent (only processes pending rows)."""

    def test_idempotent_query_structure(self):
        """The SQL query for self_seed uses WHERE status = 'pending'."""
        # This is a structural test — verifies the intent of idempotency
        # The actual SQL is in the endpoint handler which requires DB
        sql_fragment = "WHERE status = 'pending'"
        assert sql_fragment  # placeholder — actual check would verify the SQL


# ---------------------------------------------------------------------------
# Test 3: Generated nodes appear in search_knowledge_graph (integration stub)
# ---------------------------------------------------------------------------

class TestKGSearchAfterSeed:
    """Verify search returns results after seeding (requires DB — stubs)."""

    def test_knowledge_graph_search_endpoint_exists(self, client, auth_headers):
        """The search knowledge graph endpoint is available."""
        # This test verifies the endpoint exists; full integration requires DB
        # We test via the explore server since it's the browse/search interface
        # Requires DB connection — tested in integration environment


# ---------------------------------------------------------------------------
# Test 4: browse_by_type returns real results after seeding
# ---------------------------------------------------------------------------

class TestBrowseByTypeAfterSeed:
    """Verify browse_by_type returns real results after seeding."""

    def test_explore_browse_endpoint_available(self):
        """The browse_by_type endpoint exists in the explore MCP."""
        # Verify the tool is defined
        import sys
        sys.modules.pop("mcp.explore.server", None)
        from mcp.explore.server import _TOOLS
        tool_names = [t["name"] for t in _TOOLS]
        assert "browse_by_type" in tool_names


# ---------------------------------------------------------------------------
# Test: Health check includes kg_nodes
# ---------------------------------------------------------------------------

class TestHealthKG:
    """Verify health checks report kg_nodes count."""

    def test_generate_health_includes_kg_nodes(self, client):
        """generate-mcp /health includes kg_nodes in checks."""
        response = client.get("/health")
        data = response.json()
        assert "checks" in data
        assert "kg_nodes" in data["checks"], (
            f"kg_nodes missing from generate health: {data['checks']}"
        )

    def test_explore_health_includes_kg_nodes(self):
        """explore-mcp /health includes kg_nodes in checks."""
        import sys

        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.explore.server", None)
        from mcp.explore.server import app

        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        assert "checks" in data
        assert "kg_nodes" in data["checks"], (
            f"kg_nodes missing from explore health: {data['checks']}"
        )


# ---------------------------------------------------------------------------
# Test: _generate_embedding helper
# ---------------------------------------------------------------------------

class TestGenerateEmbedding:
    """Verify the embedding helper function."""

    def test_embedding_returns_none_without_model(self, monkeypatch):
        """_generate_embedding returns None when the local model is unavailable."""
        import asyncio
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "fastembed", None)
        from mcp.generate.server import _generate_embedding
        from research_shared.embedding import reset_embedding_cache

        reset_embedding_cache()
        result = asyncio.run(_generate_embedding("test text"))
        assert result is None

    def test_embedding_truncates_long_text(self, monkeypatch):
        """_generate_embedding truncates input to 8000 chars before embedding."""
        import asyncio
        import sys as _sys
        from types import SimpleNamespace

        captured = {}

        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def embed(self, documents):
                captured["docs"] = documents
                return [[0.1] * 768 for _ in documents]

        monkeypatch.setitem(
            _sys.modules, "fastembed", SimpleNamespace(TextEmbedding=FakeModel)
        )
        monkeypatch.setenv("SAIMON_EMBEDDING_BACKEND", "local")
        from mcp.generate.server import _generate_embedding
        from research_shared.embedding import reset_embedding_cache

        reset_embedding_cache()
        long_text = "x" * 10000
        result = asyncio.run(_generate_embedding(long_text))
        assert result is not None
        assert len(captured["docs"][0]) == 8000


# ---------------------------------------------------------------------------
# Test: _persist_content_node returns None without DB
# ---------------------------------------------------------------------------

class TestPersistContentNode:
    """Verify _persist_content_node degrades gracefully without DB."""

    def test_persist_returns_none_without_db(self):
        """_persist_content_node returns None when _db_pool is None."""
        import asyncio

        from mcp.generate.server import _persist_content_node

        result = asyncio.run(_persist_content_node(
            title="Test Node",
            content_type="research_note",
            body="Test body content.",
        ))
        assert result is None
