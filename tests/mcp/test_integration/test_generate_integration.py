"""Integration tests for generate-mcp — LLM and seed_data wiring.

Verifies that generate-mcp can be injected with a real LLMClient and
that content types are sourced from seed_data.py.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_generate_app(monkeypatch, api_key):
    """Reload the generate-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("mcp.generate.server", None)
    from mcp.generate.server import app
    return app


# ---------------------------------------------------------------------------
# Content type sourcing from seed_data
# ---------------------------------------------------------------------------

class TestSeedDataContentTypes:
    """Content types in generate-mcp should come from seed_data.py."""

    def test_list_content_types_matches_seed_data(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """list_content_types returns types from seed_data.CONTENT_TYPES."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "any",
                "parameters": {},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        types = data["data"]["types"]
        type_names = {t["name"] for t in types}

        # All bootstrapped content types should be present
        from research_shared.seed_data import CONTENT_TYPES as SEED_TYPES
        seed_names = {ct["name"] for ct in SEED_TYPES}
        for name in seed_names:
            assert name in type_names, f"Missing content type: {name}"

    def test_get_content_type_schema_uses_seed_data(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """get_content_type_schema returns params from seed_data."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/get_content_type_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "any",
                "parameters": {"type_name": "blog_post"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        schema = data["data"]
        assert schema["name"] == "blog_post"
        assert "required_params" in schema
        assert "optional_params" in schema
        # Verify it has the seed_data structure (list of dicts, not plain list)
        assert isinstance(schema["required_params"], list)
        assert isinstance(schema["required_params"][0], dict)
        assert "name" in schema["required_params"][0]

    def test_get_content_type_schema_rejects_unknown_type(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Unknown content type returns error."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/get_content_type_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "any",
                "parameters": {"type_name": "nonexistent_type_xyz"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# LLM backend injection
# ---------------------------------------------------------------------------

class TestLLMBackendInjection:
    """generate-mcp should support injecting an LLMClient backend."""

    def test_set_llm_client_function_exists(self):
        """Module has set_llm_client function for dependency injection."""
        sys.modules.pop("mcp.generate.server", None)
        from mcp.generate import server

        assert hasattr(server, "set_llm_client"), (
            "generate.server should expose set_llm_client()"
        )
        assert callable(server.set_llm_client)

    def test_generate_content_uses_llm_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_llm
    ):
        """When LLM is injected, generate_content calls it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import mcp.generate.server as server_mod
        server_mod._llm_client = mock_llm  # inject directly
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {
                    "prompt": "Write about AI governance",
                    "tone": "analytical",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify LLM was called (single-turn with skip_critique=True, #38)
        assert mock_llm.generate.call_count == 1
        # First call is generation, second is self-critique review
        first_call = mock_llm.generate.call_args_list[0]
        prompt_arg = first_call[0][0] if first_call[0] else first_call[1].get("prompt", "")
        assert "AI governance" in prompt_arg
        assert "blog" in prompt_arg.lower()

    def test_generate_content_degraded_without_llm(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without LLM injected, generate_content returns degraded response."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        from mcp.generate.server import app
        client = TestClient(app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI governance"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        # Should succeed but indicate degradation (no LLM injected)
        assert data["status"] in ("success", "degraded")

    def test_generate_content_handles_llm_error(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """LLM errors are caught and returned as error responses."""
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)
        from research_shared.llm import LLMError

        failing_llm = MagicMock()
        failing_llm.generate = AsyncMock(
            side_effect=LLMError("API timeout", code="TIMEOUT")
        )

        import mcp.generate.server as server_mod
        server_mod._llm_client = failing_llm
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("error", "degraded")


# ---------------------------------------------------------------------------
# store_content user_id scoping (#61)
# ---------------------------------------------------------------------------

class TestStoreContentUserScoping:
    """store_content should accept and persist optional user_id."""

    def test_store_content_with_user_id_passes_to_db(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """store_content with user_id includes it in the INSERT."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import mcp.generate.server as server_mod
        server_mod._db_pool = mock_db
        # Mock embedding generation to avoid network calls
        server_mod._generate_embedding = AsyncMock(return_value=[0.1] * 1536)
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/store_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {
                    "title": "Spencer Personal Note",
                    "content_type": "research_note",
                    "body": "Private content for Spencer only.",
                    "user_id": "bc410a6a-ca2f-4e6d-9024-2c6b0944c42f",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["node_id"] is not None

        # Verify user_id was passed to DB execute
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        # The SQL should include user_id column
        sql = call_args[0]
        assert "user_id" in sql, f"SQL should include user_id column: {sql}"
        # The last positional arg should be the user_id UUID
        params = call_args[1:]
        assert "bc410a6a-ca2f-4e6d-9024-2c6b0944c42f" in str(params), (
            f"user_id should be in params: {params}"
        )

    def test_store_content_without_user_id_still_works(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """store_content without user_id is backward-compatible (NULL)."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import mcp.generate.server as server_mod
        server_mod._db_pool = mock_db
        server_mod._generate_embedding = AsyncMock(return_value=[0.1] * 1536)
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/store_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {
                    "title": "Shared Note",
                    "content_type": "research_note",
                    "body": "Public shared content.",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        # Should still work — user_id defaults to None/NULL
        mock_db.execute.assert_called_once()
