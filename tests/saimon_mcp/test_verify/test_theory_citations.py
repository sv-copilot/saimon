"""Tests for precise theory-citation verification (SAIMON-VERIFY-THEORY-CITATIONS-1, #211).

Handoff §7 gap 2: ``verify_claim`` returned ``inconclusive`` for theory/citation
claims because shadow indexes returned unrelated GitHub archives. The fix
anchors theory claims on seeded ``source`` nodes (exact title/DOI) or a ``doi:``
passthrough before falling back to noisy full-text shadow search, and records the
anchor path in ``verify.theory_anchor`` for traceability.

These tests pin:
1. DOI-first path — a DOI claim verifies ``supported`` without a full-text query.
2. Source-node-first path — a seeded ``source`` node verifies via
   ``source_corroboration``.
3. Short-circuit — no keyword-shaped full-text shadow query when anchored.
4. ``theory_anchor`` audit field — records the anchor path for every verdict.
"""

from __future__ import annotations

import sys
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_key() -> str:
    return "sk-test-theory-citations"


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def verify_server(monkeypatch, api_key):
    """Reload verify-mcp with a clean module state for monkeypatching."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
    sys.modules.pop("saimon_mcp.verify.server", None)
    sys.modules.pop("saimon_mcp.verify", None)
    from saimon_mcp.verify import server as srv

    return srv


@pytest.fixture
def client(verify_server):
    return TestClient(verify_server.app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}


def _post_claim(client, sample_trace_id, auth_headers, claim, **params):
    return client.post(
        "/tools/verify_claim",
        json={
            "trace_id": sample_trace_id,
            "content_type": "verify",
            "parameters": {"claim": claim, **params},
        },
        headers=auth_headers,
    )


class TestTheoryAnchorDetection:
    """Unit tests for the pure anchor-detection helpers."""

    def test_seeded_source_matches_by_doi(self, verify_server):
        anchor = verify_server._detect_theory_anchor(
            "Self-Determination Theory (doi:10.1007/978-1-4899-2271-7) "
            "explains intrinsic motivation."
        )
        assert anchor["anchor"] == "seeded_node"
        assert anchor["source_node"]["key"] == "source/deci-ryan-1985"
        assert anchor["doi"] == "10.1007/978-1-4899-2271-7"
        assert anchor["theory"] == "self_determination_theory"

    def test_seeded_source_matches_by_exact_title(self, verify_server):
        anchor = verify_server._detect_theory_anchor(
            "Intrinsic Motivation and Self-Determination in Human Behavior "
            "by Deci and Ryan (1985) argues autonomy supports motivation."
        )
        assert anchor["anchor"] == "seeded_node"
        assert anchor["source_node"]["key"] == "source/deci-ryan-1985"

    def test_unseeded_doi_uses_cache_doi_anchor(self, verify_server):
        anchor = verify_server._detect_theory_anchor(
            "A meta-analysis (10.1016/j.jvb.2007.09.001) links engagement to "
            "job resources."
        )
        assert anchor["anchor"] == "cache_doi"
        assert anchor["doi"] == "10.1016/j.jvb.2007.09.001"
        assert anchor["source_node"] is None

    def test_non_theory_claim_uses_full_text_anchor(self, verify_server):
        anchor = verify_server._detect_theory_anchor("The Earth orbits the Sun.")
        assert anchor["anchor"] == "full_text"
        assert anchor["doi"] is None

class TestTheoryDoiFirst:
    """A claim with a DOI verifies supported without a full-text shadow query."""

    def test_doi_claim_verifies_supported_without_fulltext_query(
        self, verify_server, client, sample_trace_id, auth_headers, monkeypatch
    ):
        non_seeded_doi = "10.1016/j.jvb.2007.09.001"
        queries: list[str] = []

        async def fake_search(claim, limit=5):
            queries.append(claim)
            return (
                [
                    {
                        "title": "Work engagement: A meta-analysis",
                        "doi": non_seeded_doi,
                        "source_index": "internet_archive",
                    }
                ],
                False,
            )

        monkeypatch.setattr(verify_server, "_search_sources_with_status", fake_search)

        response = _post_claim(
            client,
            sample_trace_id,
            auth_headers,
            f"Work engagement is positively linked to job resources "
            f"({non_seeded_doi}).",
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["overall_verdict"] == "supported"
        assert data["data"]["theory_anchor"] == "cache_doi"
        # Only a precise doi: passthrough was issued — never a keyword-shaped
        # full-text query of the prose claim.
        assert queries == [f"doi:{non_seeded_doi}"]
        shadow = next(
            v
            for v in data["data"]["verifications"]
            if v["method"] == "doi_cache_corroboration"
        )
        assert shadow["verdict"] == "supported"


class TestTheorySourceNodeFirst:
    """A claim matching a seeded source node verifies via source_corroboration."""

    def test_seeded_source_node_verifies_via_source_corroboration(
        self, verify_server, client, sample_trace_id, auth_headers, monkeypatch
    ):
        queries: list[str] = []

        async def fake_search(claim, limit=5):
            queries.append(claim)
            return ([], False)

        monkeypatch.setattr(verify_server, "_search_sources_with_status", fake_search)

        response = _post_claim(
            client,
            sample_trace_id,
            auth_headers,
            "Intrinsic Motivation and Self-Determination in Human Behavior "
            "by Deci and Ryan argues autonomy supports intrinsic motivation.",
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["overall_verdict"] == "supported"
        assert data["data"]["theory_anchor"] == "seeded_node"
        source = next(
            v
            for v in data["data"]["verifications"]
            if v["method"] == "source_corroboration"
        )
        assert source["verdict"] == "supported"
        # Short-circuit: the seeded source node anchored the verdict, so no
        # shadow search of any kind was attempted.
        assert queries == []


class TestTheoryAnchorAuditField:
    """theory_anchor is recorded for every theory verdict."""

    def test_full_text_anchor_for_non_theory_claim(
        self, verify_server, client, sample_trace_id, auth_headers, monkeypatch
    ):
        queries: list[str] = []

        async def fake_search(claim, limit=5):
            queries.append(claim)
            return ([], False)

        monkeypatch.setattr(verify_server, "_search_sources_with_status", fake_search)

        response = _post_claim(
            client,
            sample_trace_id,
            auth_headers,
            "The Earth orbits the Sun.",
            use_shadow_sources=True,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["theory_anchor"] == "full_text"
        assert queries == ["The Earth orbits the Sun."]

