"""Tests for shadow source integration in verify-mcp."""

import uuid

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-shadow-verify-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the verify-mcp FastAPI app."""
    import sys
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
    sys.modules.pop("saimon_mcp.verify.server", None)
    sys.modules.pop("saimon_mcp.verify", None)
    from research_shared.shadow_registry import reset_shadow_registry
    reset_shadow_registry()
    from saimon_mcp.verify.server import app
    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}


# ---------------------------------------------------------------------------
# Shadow source corroboration method
# ---------------------------------------------------------------------------


class TestShadowSourceCorroboration:
    """Tests for shadow_source_corroboration verification method."""

    def test_method_registered_in_list(self, client, sample_trace_id, auth_headers):
        """shadow_source_corroboration appears in the methods list."""
        response = client.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers=auth_headers,
        )
        data = response.json()
        method_names = {m["name"] for m in data["data"]["methods"]}
        assert "shadow_source_corroboration" in method_names

    def test_method_has_reliability_score(self, client, sample_trace_id, auth_headers):
        """shadow_source_corroboration has a reliability score."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "shadow_source_corroboration"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert "reliability" in data["data"]
        assert 0.0 <= data["data"]["reliability"] <= 1.0

    def test_verify_claim_supports_use_shadow_sources(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim accepts use_shadow_sources parameter."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "The Earth orbits the Sun.",
                    "use_shadow_sources": True,
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_verify_claim_without_use_shadow_sources_behaves_normally(
        self, client, sample_trace_id, auth_headers
    ):
        """Default behavior without use_shadow_sources is unchanged."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Water boils at 100°C at sea level.",
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "overall_verdict" in data["data"]

    def test_shadow_sources_disabled_by_env(
        self, client, sample_trace_id, monkeypatch
    ):
        """When SHADOW_SOURCES_ENABLED=false, shadow method is excluded."""
        import sys
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "false")
        sys.modules.pop("saimon_mcp.verify.server", None)
        sys.modules.pop("saimon_mcp.verify", None)
        from saimon_mcp.verify.server import app
        tc = TestClient(app)

        response = tc.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers={"X-Saimon-API-Key": "sk-test-shadow-verify-key"},
        )
        data = response.json()
        method_names = {m["name"] for m in data["data"]["methods"]}
        assert "shadow_source_corroboration" not in method_names
