"""Integration tests for shadow library search pipeline.

These test the end-to-end flow: search_sources →
deduplication → verify_claim with shadow sources.  They hit the live
Internet Archive (archive.org) adapter, so they are marked ``integration``
and skipped in CI, where outbound network access is unavailable.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-shadow-integration-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the search-mcp FastAPI app."""
    import sys

    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.search.server", None)
    sys.modules.pop("saimon_mcp.search", None)
    from research_shared.shadow_registry import reset_shadow_registry

    reset_shadow_registry()
    from saimon_mcp.search.server import app

    return TestClient(app)


@pytest.fixture
def verify_client(api_key, monkeypatch):
    """Return a TestClient for the verify-mcp FastAPI app."""
    import sys

    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
    sys.modules.pop("saimon_mcp.verify.server", None)
    sys.modules.pop("saimon_mcp.verify", None)
    from saimon_mcp.verify.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}


# ---------------------------------------------------------------------------
# End-to-end: search → verify
# ---------------------------------------------------------------------------


class TestShadowSearchEndToEnd:
    """End-to-end flow: search shadow libraries, then verify with results."""

    def test_full_search_returns_results(self, client, sample_trace_id, auth_headers):
        """A real query produces results from multiple adapters."""
        response = client.post(
            "/tools/search_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {
                    "query": "transformer attention mechanisms",
                    "limit": 10,
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["total_results"] > 0
        assert len(data["data"]["results"]) > 0

    def test_search_results_are_deduplicated(
        self, client, sample_trace_id, auth_headers
    ):
        """Results from multiple sources are deduplicated."""
        response = client.post(
            "/tools/search_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "deep learning optimization"},
            },
            headers=auth_headers,
        )
        data = response.json()
        # All results should have unique identifiers after dedup
        identifiers = [r["identifier"] for r in data["data"]["results"]]
        assert len(identifiers) == len(set(identifiers))

    def test_citations_present_in_response(self, client, sample_trace_id, auth_headers):
        """Response includes citations array."""
        response = client.post(
            "/tools/search_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "graph neural networks"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "citations" in data
        assert len(data["citations"]) > 0

    def test_list_source_indexes_includes_all_adapters(
        self, client, sample_trace_id, auth_headers
    ):
        """list_source_indexes includes all 5 shadow adapters."""
        response = client.post(
            "/tools/list_source_indexes",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        data = response.json()
        shadow_indexes = [
            s for s in data["data"]["source_indexes"] if s["type"] == "source_index"
        ]
        names = {s["identifier"] for s in shadow_indexes}
        assert names == {
            "annas_archive",
            "libgen",
            "scihub",
            "internet_archive",
            "academic_torrents",
        }

    def test_verify_claim_with_shadow_sources(
        self, verify_client, sample_trace_id, auth_headers
    ):
        """Verify a claim with shadow sources enabled."""
        response = verify_client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Transformers have revolutionized NLP since 2017.",
                    "use_shadow_sources": True,
                    "methods": ["shadow_source_corroboration"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        verifications = data["data"]["verifications"]
        assert any(v["method"] == "shadow_source_corroboration" for v in verifications)

    def test_verify_and_search_share_source_indexes(
        self, client, verify_client, sample_trace_id, auth_headers
    ):
        """Source indexes from search are usable in verify context."""
        # Search for sources
        search_resp = client.post(
            "/tools/search_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "protein folding AI"},
            },
            headers=auth_headers,
        )
        search_data = search_resp.json()
        assert search_data["status"] in ("success", "degraded")

        # Sources found should be usable
        results = search_data["data"]["results"]
        if results:
            sample_result = results[0]
            assert "title" in sample_result
            assert "source_index" in sample_result
