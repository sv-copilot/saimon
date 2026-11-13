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
    from research_shared.archive_registry import reset_archive_registry
    reset_archive_registry()
    from saimon_mcp.verify.server import app
    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}


# ---------------------------------------------------------------------------
# Shadow source corroboration method
# ---------------------------------------------------------------------------


class TestShadowSourceCorroboration:
    """Tests for the DOI-cache corroboration method."""

    def test_method_registered_in_list(self, client, sample_trace_id, auth_headers):
        """doi_cache_corroboration appears in the methods list."""
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
        assert "doi_cache_corroboration" in method_names

    def test_method_has_reliability_score(self, client, sample_trace_id, auth_headers):
        """doi_cache_corroboration has a reliability score."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "doi_cache_corroboration"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert "reliability" in data["data"]
        assert 0.0 <= data["data"]["reliability"] <= 1.0

    def test_verify_claim_supports_use_doi_caches(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim accepts use_doi_caches parameter."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "The Earth orbits the Sun.",
                    "use_doi_caches": True,
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_verify_claim_without_use_doi_caches_behaves_normally(
        self, client, sample_trace_id, auth_headers
    ):
        """Default behavior without use_doi_caches is unchanged."""
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

    def test_doi_caches_disabled_by_env(
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
        assert "doi_cache_corroboration" not in method_names
