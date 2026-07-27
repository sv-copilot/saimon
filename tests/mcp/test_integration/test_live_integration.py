"""Live integration tests — validate real PostgreSQL + DeepSeek connectivity.

These tests require:
- DATABASE_URL pointing to a live PostgreSQL 16 instance
- DEEPSEEK_API_KEY for LLM calls
- LIVE_TEST=1 environment variable set

When LIVE_TEST is not set, all tests are skipped.

Run:
    LIVE_TEST=1 DATABASE_URL=postgresql://... DEEPSEEK_API_KEY=sk-... pytest tests/mcp/test_integration/test_live_integration.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# live-test gate
# ---------------------------------------------------------------------------

LIVE_TEST = os.getenv("LIVE_TEST", "").lower() in ("1", "true", "yes")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not LIVE_TEST,
    reason="Set LIVE_TEST=1 and provide DATABASE_URL + DEEPSEEK_API_KEY to run live tests",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fresh_app(monkeypatch, mcp_name, api_key="sk-live-test-key"):
    """Reload an MCP app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    if DEEPSEEK_API_KEY:
        monkeypatch.setenv("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY)
    if DATABASE_URL:
        monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    module_name = f"mcp.{mcp_name}.server"
    sys.modules.pop(module_name, None)
    import importlib
    mod = importlib.import_module(module_name)
    return mod.app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def live_db_pool():
    """Return a real DatabasePool connected to PostgreSQL."""
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    from research_shared.db import DatabaseConfig, DatabasePool
    cfg = DatabaseConfig(database_url=DATABASE_URL)
    pool = DatabasePool(cfg)
    yield pool


@pytest.fixture
def live_llm_client():
    """Return a real LLMClient configured for DeepSeek."""
    if not DEEPSEEK_API_KEY:
        pytest.skip("DEEPSEEK_API_KEY not set")

    from research_shared.llm import LLMClient, LLMConfig
    cfg = LLMConfig(api_key=DEEPSEEK_API_KEY)
    client = LLMClient(cfg)
    yield client


# ---------------------------------------------------------------------------
# Database live tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLiveDatabase:
    """Validate real PostgreSQL connectivity via DatabasePool."""

    async def test_connect_and_query(self, live_db_pool):
        """DatabasePool can connect and run SELECT 1."""
        row = await live_db_pool.fetchval("SELECT 1")
        assert row == 1

    async def test_fetch_returns_dicts(self, live_db_pool):
        """fetch() returns rows as dicts."""
        rows = await live_db_pool.fetch("SELECT 1 AS num")
        assert len(rows) == 1
        assert rows[0]["num"] == 1
        assert isinstance(rows[0], dict)

    async def test_fetchrow_returns_single(self, live_db_pool):
        """fetchrow() returns a single row dict."""
        row = await live_db_pool.fetchrow("SELECT 2 AS val")
        assert row is not None
        assert row["val"] == 2

    async def test_execute_ddl(self, live_db_pool):
        """execute() can run DDL statements."""
        result = await live_db_pool.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _live_test (id SERIAL PRIMARY KEY, name TEXT)"
        )
        assert result is not None

    async def test_close_does_not_crash(self, live_db_pool):
        """close() works without errors."""
        await live_db_pool.close()

    async def test_reconnect_after_close(self, live_db_pool):
        """Pool can be used again after close and re-init."""
        await live_db_pool.close()
        # Force re-init
        live_db_pool._pool = None
        result = await live_db_pool.fetchval("SELECT 42")
        assert result == 42
        await live_db_pool.close()


# ---------------------------------------------------------------------------
# LLM live tests
# ---------------------------------------------------------------------------

class TestLiveLLM:
    """Validate real DeepSeek API connectivity via LLMClient."""

    def test_health_check(self, live_llm_client):
        """LLMClient.health_check() returns True with valid API key."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            live_llm_client.health_check()
        )
        assert result is True

    def test_generate_returns_string(self, live_llm_client):
        """generate() returns a non-empty string."""
        import asyncio

        async def _run():
            return await live_llm_client.generate(
                "Say hello in exactly one word.",
                max_tokens=10,
                temperature=0.0,
            )

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Full core workflow — request → generate → evaluate → verify → export
# ---------------------------------------------------------------------------

class TestLiveCoreWorkflow:
    """End-to-end test of the full Saimon core workflow."""

    def test_full_generate_pipeline(self, monkeypatch, live_llm_client):
        """Generate content via live LLM through the generate-mcp."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "generate", "sk-live-test-key")
        from mcp.generate.server import set_llm_client
        set_llm_client(live_llm_client)

        client = TestClient(app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": "live-test-001",
                "content_type": "blog_post",
                "parameters": {
                    "prompt": "Write a one-sentence intro about AI.",
                    "tone": "professional",
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"] is not None

    def test_full_evaluate_pipeline(self, monkeypatch, live_llm_client):
        """Evaluate content via live LLM through the evaluate-mcp."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "evaluate", "sk-live-test-key")
        from mcp.evaluate.server import set_llm_client
        set_llm_client(live_llm_client)

        client = TestClient(app)
        sample_content = "Artificial intelligence is transforming how we work and live."

        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": "live-test-002",
                "content_type": "blog_post",
                "parameters": {
                    "content": sample_content,
                    "criteria": ["clarity", "conciseness"],
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_full_verify_pipeline(self, monkeypatch, live_llm_client):
        """Verify a claim via live LLM through the verify-mcp."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "verify", "sk-live-test-key")
        from mcp.verify.server import set_llm_client
        set_llm_client(live_llm_client)

        client = TestClient(app)

        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": "live-test-003",
                "content_type": "claim",
                "parameters": {
                    "claim": "The Earth orbits the Sun.",
                    "methods": ["logical_consistency"],
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_full_export_pipeline(self, monkeypatch):
        """Export content through the export-mcp (no LLM needed)."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "export", "sk-live-test-key")
        client = TestClient(app)

        sample = "## Hello World\n\nThis is **bold** text."
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": "live-test-004",
                "content_type": "blog_post",
                "parameters": {
                    "content": sample,
                    "format": "markdown",
                    "include_title": True,
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_full_search_pipeline(self, monkeypatch, live_db_pool):
        """Search the knowledge graph through search-mcp."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "search", "sk-live-test-key")
        from mcp.search.server import set_db_pool
        set_db_pool(live_db_pool)

        client = TestClient(app)

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": "live-test-005",
                "content_type": "any",
                "parameters": {"query": "test", "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_full_explore_pipeline(self, monkeypatch, live_db_pool):
        """Explore the knowledge graph through explore-mcp."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "explore", "sk-live-test-key")
        from mcp.explore.server import set_db_pool
        set_db_pool(live_db_pool)

        client = TestClient(app)

        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": "live-test-006",
                "content_type": "any",
                "parameters": {"query": "knowledge", "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_end_to_end_core_workflow(self, monkeypatch, live_llm_client, live_db_pool):
        """Full core workflow: generate → evaluate → verify → export.

        This test validates the complete Saimon pipeline with live backends.
        """
        from fastapi.testclient import TestClient

        # ── Step 1: Generate ──
        gen_app = _fresh_app(monkeypatch, "generate", "sk-live-test-key")
        from mcp.generate.server import set_llm_client as set_gen_llm
        set_gen_llm(live_llm_client)

        gen_client = TestClient(gen_app)
        gen_resp = gen_client.post(
            "/tools/generate_content",
            json={
                "trace_id": "e2e-test-001",
                "content_type": "blog_post",
                "parameters": {
                    "prompt": "Write one paragraph about the future of technology.",
                    "tone": "professional",
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert gen_data["status"] in ("success", "degraded")
        content = gen_data.get("data", {}).get("content", gen_data.get("data", ""))

        # ── Step 2: Evaluate ──
        eval_app = _fresh_app(monkeypatch, "evaluate", "sk-live-test-key")
        from mcp.evaluate.server import set_llm_client as set_eval_llm
        set_eval_llm(live_llm_client)

        eval_client = TestClient(eval_app)
        eval_resp = eval_client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": "e2e-test-001",
                "content_type": "blog_post",
                "parameters": {
                    "content": str(content)[:2000],
                    "criteria": ["clarity", "completeness", "tone_match"],
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        assert eval_data["status"] in ("success", "degraded")

        # ── Step 3: Verify ──
        verify_app = _fresh_app(monkeypatch, "verify", "sk-live-test-key")
        from mcp.verify.server import set_llm_client as set_ver_llm
        set_ver_llm(live_llm_client)

        verify_client = TestClient(verify_app)
        verify_resp = verify_client.post(
            "/tools/verify_claim",
            json={
                "trace_id": "e2e-test-001",
                "content_type": "claim",
                "parameters": {
                    "claim": str(content)[:500],
                    "methods": ["source_corroboration", "logical_consistency"],
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert verify_resp.status_code == 200
        verify_data = verify_resp.json()
        assert verify_data["status"] in ("success", "degraded")

        # ── Step 4: Export ──
        export_app = _fresh_app(monkeypatch, "export", "sk-live-test-key")
        export_client = TestClient(export_app)
        export_resp = export_client.post(
            "/tools/export_content",
            json={
                "trace_id": "e2e-test-001",
                "content_type": "blog_post",
                "parameters": {
                    "content": str(content),
                    "format": "json",
                    "include_citations": True,
                },
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert export_resp.status_code == 200
        export_data = export_resp.json()
        assert export_data["status"] == "success"
        assert "content" in str(export_data["data"]).lower() or export_data["data"] is not None


# ---------------------------------------------------------------------------
# Degradation tests — verify fallback when backends are absent
# ---------------------------------------------------------------------------

class TestLiveDegradation:
    """Verify MCPs degrade gracefully when backends are not injected."""

    def test_search_degraded_without_db(self, monkeypatch):
        """search-mcp returns degraded status without DB injection."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "search", "sk-live-test-key")
        client = TestClient(app)

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": "deg-test-001",
                "content_type": "any",
                "parameters": {"query": "test"},
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_generate_degraded_without_llm(self, monkeypatch):
        """generate-mcp returns error without LLM injection."""
        from fastapi.testclient import TestClient

        app = _fresh_app(monkeypatch, "generate", "sk-live-test-key")
        client = TestClient(app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": "deg-test-002",
                "content_type": "blog_post",
                "parameters": {"prompt": "Hello"},
            },
            headers={"X-Saimon-API-Key": "sk-live-test-key"},
        )
        assert response.status_code == 200
        data = response.json()
        # Without LLM, should degrade gracefully (not crash)
        assert data["status"] in ("degraded", "error")
