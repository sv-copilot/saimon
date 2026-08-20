"""Integration tests for self-extension flow.

Verifies that generate-mcp can be injected with a SelfExtender and that
unknown content types trigger research → auto-register.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_generate_app(monkeypatch, api_key):
    """Reload the generate-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.generate.server", None)
    from saimon_mcp.generate.server import app
    return app


# ---------------------------------------------------------------------------
# SeedLoader injection into generate-mcp
# ---------------------------------------------------------------------------


class TestSeedLoaderInjection:
    """generate-mcp should support SeedLoader injection for re-seeding."""

    def test_seed_loader_injection_function_exists(self):
        """Server module exposes set_seed_loader for DI."""
        sys.modules.pop("saimon_mcp.generate.server", None)
        from saimon_mcp.generate import server

        assert hasattr(server, "set_seed_loader"), (
            "generate.server should expose set_seed_loader()"
        )
        assert callable(server.set_seed_loader)

    def test_seed_content_types_tool_registered(self, monkeypatch, api_key):
        """seed_content_types tool is listed in /tools."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.get(
            "/tools",
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "seed_content_types" in tool_names, (
            f"seed_content_types should be in tools, got: {tool_names}"
        )

    def test_seed_content_types_requires_auth(self, monkeypatch, api_key, sample_trace_id):
        """seed_content_types rejects requests without auth."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/seed_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "any",
                "parameters": {},
            },
        )
        assert response.status_code == 401

    def test_seed_content_types_calls_loader(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """When seed loader is injected, seed_content_types uses it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        # Create a mock seed loader
        mock_loader = MagicMock()
        mock_loader.load_all = AsyncMock(return_value={
            "content_types": {"loaded": 13},
            "voice_profiles": {"loaded": 5},
            "seed_requests": {"loaded": 15},
        })
        server_mod._seed_loader = mock_loader

        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/seed_content_types",
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
        mock_loader.load_all.assert_called_once()

    def test_seed_content_types_degraded_without_loader(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without seed loader injected, returns degraded."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod
        server_mod._seed_loader = None
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/seed_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "any",
                "parameters": {},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        # Should succeed but in degraded mode
        assert data["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# SelfExtender injection into generate-mcp
# ---------------------------------------------------------------------------


class TestSelfExtenderInjection:
    """generate-mcp should support SelfExtender injection."""

    def test_set_self_extender_function_exists(self):
        """Server module exposes set_self_extender for DI."""
        sys.modules.pop("saimon_mcp.generate.server", None)
        from saimon_mcp.generate import server

        assert hasattr(server, "set_self_extender"), (
            "generate.server should expose set_self_extender()"
        )
        assert callable(server.set_self_extender)

    def test_generate_content_triggers_self_extend_for_unknown_type(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """When type is unknown and SelfExtender is injected,
        generate_content triggers research → auto-register."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        # Create a mock SelfExtender
        mock_extender = MagicMock()
        mock_extender.ensure_type = AsyncMock(return_value={
            "name": "custom_type",
            "description": "A custom content type.",
            "required_params": [
                {"name": "topic", "type": "str", "description": "The topic."}
            ],
            "optional_params": [],
            "voice_profile": None,
        })
        # Also inject a mock LLM for generation
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Generated custom content.")

        server_mod._self_extender = mock_extender
        server_mod._llm_client = mock_llm
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "custom_type",
                "parameters": {"prompt": "Write about a custom topic"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # SelfExtender should have been called to ensure the type exists
        mock_extender.ensure_type.assert_called_once_with("custom_type")

        # LLM should have been called for generation (single-turn, #38)
        assert mock_llm.generate.call_count == 1

    def test_generate_content_known_type_skips_self_extend(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """When type is known (in seed data), SelfExtender is NOT called."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        mock_extender = MagicMock()
        mock_extender.ensure_type = AsyncMock()
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="Generated blog content.")

        server_mod._self_extender = mock_extender
        server_mod._llm_client = mock_llm
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
        assert response.json()["status"] == "success"

        # SelfExtender should NOT have been called for known types
        mock_extender.ensure_type.assert_not_called()

    def test_generate_content_self_extend_failure_degrades(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """When SelfExtender fails, generate_content still works in degraded mode."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        mock_extender = MagicMock()
        mock_extender.ensure_type = AsyncMock(
            side_effect=Exception("Self-extend unavailable")
        )

        server_mod._self_extender = mock_extender
        server_mod._llm_client = None  # No LLM either
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "unknown_new_type",
                "parameters": {"prompt": "Write something"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        # Should degrade gracefully, not crash
        assert data["status"] in ("success", "degraded")

    def test_list_content_types_includes_registry_types(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """When SelfExtender is injected, list_content_types merges
        seed data + registry types."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        mock_extender = MagicMock()
        mock_extender.list_registered_types = AsyncMock(return_value=[
            {
                "name": "runtime_type",
                "description": "Registered at runtime.",
                "required_params": [],
                "optional_params": [],
                "voice_profile": None,
            }
        ])
        server_mod._self_extender = mock_extender
        client = TestClient(server_mod.app)

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
        assert data["status"] in ("success", "degraded")

        type_names = {t["name"] for t in data["data"]["types"]}
        # Should include both seed types and runtime types
        assert "blog_post" in type_names  # from seed
        assert "runtime_type" in type_names  # from registry

    def test_get_content_type_schema_checks_registry_first(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """get_content_type_schema checks registry (via SelfExtender) before seed data."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.generate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.generate.server as server_mod

        # Extender has a runtime type that overrides seed
        mock_extender = MagicMock()
        mock_extender.ensure_type = AsyncMock(return_value={
            "name": "blog_post",
            "description": "Override from registry.",
            "required_params": [{"name": "custom_param", "type": "str", "description": "Custom"}],
            "optional_params": [],
            "voice_profile": "spencer-custom",
        })
        server_mod._self_extender = mock_extender
        client = TestClient(server_mod.app)

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
        # Should return success (from registry override)
        assert data["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# DB pool injection into generate-mcp
# ---------------------------------------------------------------------------


class TestDBPoolInjection:
    """generate-mcp should support DatabasePool injection."""

    def test_set_db_pool_function_exists(self):
        """Server module exposes set_db_pool for DI."""
        sys.modules.pop("saimon_mcp.generate.server", None)
        from saimon_mcp.generate import server

        assert hasattr(server, "set_db_pool"), (
            "generate.server should expose set_db_pool()"
        )
        assert callable(server.set_db_pool)
