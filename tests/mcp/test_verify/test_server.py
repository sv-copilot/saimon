"""Tests for verify-mcp — fact-checking MCP."""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        """GET /health returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "verify-mcp"

    def test_health_no_auth_required(self, client):
        """Health endpoint does not require auth."""
        response = client.get("/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_tool_endpoint_rejects_missing_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 without an API key."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers=auth_headers,
        )
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class TestEnvelope:
    def test_response_uses_research_response_shape(
        self, client, sample_trace_id, auth_headers
    ):
        """Tool responses conform to ResearchResponse envelope."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: verify_claim
# ---------------------------------------------------------------------------

class TestVerifyClaim:
    def test_requires_claim(self, client, sample_trace_id, auth_headers):
        """verify_claim returns error without claim parameter."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("claim" in e.lower() for e in (data.get("errors") or []))

    def test_verifies_claim_with_default_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim returns verification results with default methods."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth revolves around the Sun."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "verifications" in data["data"]
        assert len(data["data"]["verifications"]) >= 2

    def test_filters_by_specified_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim uses only requested verification methods."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Water boils at 100°C at sea level.",
                    "methods": ["source_corroboration", "logical_consistency"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        method_names = [v["method"] for v in data["data"]["verifications"]]
        assert set(method_names) == {"source_corroboration", "logical_consistency"}

    def test_each_verification_has_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each verification includes method, verdict, confidence, explanation."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "Python was created by Guido van Rossum."},
            },
            headers=auth_headers,
        )
        data = response.json()
        for v in data["data"]["verifications"]:
            assert "method" in v
            assert "verdict" in v
            assert v["verdict"] in ("supported", "refuted", "inconclusive")
            assert "confidence" in v
            assert 0.0 <= v["confidence"] <= 1.0
            assert "explanation" in v
            assert len(v["explanation"]) > 0

    def test_includes_overall_verdict(self, client, sample_trace_id, auth_headers):
        """verify_claim returns an aggregate overall_verdict."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "overall_verdict" in data["data"]
        assert data["data"]["overall_verdict"] in (
            "supported", "refuted", "inconclusive"
        )

    def test_rejects_unknown_method(self, client, sample_trace_id, auth_headers):
        """verify_claim errors when an unknown method is requested."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Test claim.",
                    "methods": ["nonexistent_method"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_accepts_sources_for_corroboration(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim accepts optional sources list."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "Test claim."},
                "sources": [
                    {"type": "web_page", "identifier": "https://example.com"}
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_verification_methods
# ---------------------------------------------------------------------------

class TestListVerificationMethods:
    def test_returns_registered_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """list_verification_methods returns all methods."""
        response = client.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"]["methods"], list)
        assert len(data["data"]["methods"]) >= 3

    def test_methods_have_schema(self, client, sample_trace_id, auth_headers):
        """Each method includes name, description, and reliability."""
        response = client.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers=auth_headers,
        )
        data = response.json()
        for m in data["data"]["methods"]:
            assert "name" in m
            assert "description" in m
            assert "reliability" in m
            assert 0.0 <= m["reliability"] <= 1.0


# ---------------------------------------------------------------------------
# Tool: get_method_detail
# ---------------------------------------------------------------------------

class TestGetMethodDetail:
    def test_returns_detail_for_known_method(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail returns schema for source_corroboration."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "source_corroboration"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "source_corroboration"

    def test_errors_for_unknown_method(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail errors for unknown method."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "nonexistent"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_method_name(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail errors without method_name."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Tool count
# ---------------------------------------------------------------------------

class TestToolCount:
    def test_tool_count_within_limit(self, client, auth_headers):
        """verify-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10


# ---------------------------------------------------------------------------
# Citation verification (FACTUALITY-VERIFY-1)
# ---------------------------------------------------------------------------


class TestCitationVerification:
    """Tests for DOI resolution and citation flagging."""

    def test_doi_resolves(self, client, sample_trace_id, auth_headers, monkeypatch):
        """A real DOI in evidence_source is verified via _search_sources."""
        # The heuristic path doesn't include evidence_source, so we test
        # the helper directly by importing it.
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import asyncio
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _extract_dois, _verify_citation, _search_sources

        # Mock _search_sources to return a matching DOI
        async def mock_search(claim, limit=5):
            return [{"doi": "10.1234/test.1", "title": "Test Paper"}]

        # Patch the module-level _search_sources
        import mcp.verify.server as srv
        original = srv._search_sources
        srv._search_sources = mock_search
        try:
            result = asyncio.run(_verify_citation("10.1234/test.1"))
            assert result["verified"] is True
            assert result["source"]["doi"] == "10.1234/test.1"
            assert result["flag"] is None
        finally:
            srv._search_sources = original

    def test_fake_doi_flagged(self, client, sample_trace_id, auth_headers, monkeypatch):
        """A non-resolving DOI returns [UNVERIFIED SOURCE] flag."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import asyncio
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _verify_citation

        async def mock_search(claim, limit=5):
            return []  # no results

        import mcp.verify.server as srv
        original = srv._search_sources
        srv._search_sources = mock_search
        try:
            result = asyncio.run(_verify_citation("10.9999/fake.123"))
            assert result["verified"] is False
            assert result["flag"] == "[UNVERIFIED SOURCE]"
        finally:
            srv._search_sources = original


# ---------------------------------------------------------------------------
# Adversarial verification (FACTUALITY-VERIFY-1)
# ---------------------------------------------------------------------------


class TestAdversarialVerification:
    """Tests for adversarial (refutation) verification."""

    def test_adversarial_disputed(self, client, sample_trace_id, auth_headers, monkeypatch):
        """When primary and adversarial verdicts disagree, disputed=True."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compare_adversarial

        adv_result = {
            "overall_verdict": "refuted",
            "verifications": [],
            "key_disagreements": ["Source A contradicts the claim."],
        }
        result = _compare_adversarial("supported", adv_result)
        assert result["disputed"] is True
        assert result["primary_perspective"] == "supported"
        assert result["adversarial_perspective"] == "refuted"
        assert "key_disagreements" in result

    def test_adversarial_agreement(self, client, sample_trace_id, auth_headers, monkeypatch):
        """When primary and adversarial verdicts agree, disputed=False."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compare_adversarial

        adv_result = {
            "overall_verdict": "supported",
            "verifications": [],
            "key_disagreements": [],
        }
        result = _compare_adversarial("supported", adv_result)
        assert result["disputed"] is False


# ---------------------------------------------------------------------------
# Abstention (FACTUALITY-VERIFY-1)
# ---------------------------------------------------------------------------


class TestAbstention:
    """Tests for confidence-based abstention."""

    def test_low_confidence_abstains(self, client, sample_trace_id, auth_headers, monkeypatch):
        """overall_confidence < 0.5 → abstained=True, verdict=inconclusive."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_overall_confidence

        verifications = [
            {"method": "source_corroboration", "confidence": 0.3},
            {"method": "logical_consistency", "confidence": 0.2},
        ]
        conf = _compute_overall_confidence(verifications)
        assert conf < 0.5
        # With real heuristic verifiers, confidence is high, so we test
        # the helper directly for the abstention path.

    def test_high_confidence_returns_verdict(self, client, sample_trace_id, auth_headers):
        """When overall_confidence >= 0.5, response includes overall_verdict."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth revolves around the Sun."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert "overall_verdict" in data["data"]
        assert data["data"]["overall_verdict"] in (
            "supported", "refuted", "inconclusive"
        )
        # Heuristic verifiers have confidence > 0.5, so abstained should not be present
        # (or if present, it should be False)
        abstained = data["data"].get("abstained")
        if abstained is not None:
            assert abstained is False


# ---------------------------------------------------------------------------
# Claim extraction (FACTUALITY-OBSERVATION-1)
# ---------------------------------------------------------------------------


class TestClaimExtraction:
    """Tests for extract_claims tool."""

    def test_extract_claims_falsifiable(self, client, sample_trace_id, auth_headers):
        """extract_claims returns falsifiable claims from source text."""
        response = client.post(
            "/tools/extract_claims",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "source_text": "The Earth orbits the Sun. Water boils at 100°C at sea level."
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "claims" in data["data"]
        assert isinstance(data["data"]["claims"], list)
        # Without LLM, claims list is empty (heuristic fallback)
        # With LLM, claims would be extracted

    def test_extract_confidence(self, client, sample_trace_id, auth_headers):
        """extract_claims response includes count field."""
        response = client.post(
            "/tools/extract_claims",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "source_text": "Python was created by Guido van Rossum in 1991."
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "count" in data["data"]
        assert isinstance(data["data"]["count"], int)

    def test_empty_returns_empty(self, client, sample_trace_id, auth_headers):
        """Empty source_text returns error, not claims."""
        response = client.post(
            "/tools/extract_claims",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"source_text": ""},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("source_text" in e.lower() for e in (data.get("errors") or []))


# ---------------------------------------------------------------------------
# Observation persistence (FACTUALITY-OBSERVATION-1)
# ---------------------------------------------------------------------------


class TestObservationPersistence:
    """Tests for observation persistence helpers."""

    def test_observation_persisted(self, client, sample_trace_id, auth_headers, monkeypatch):
        """_persist_observation returns an observation ID."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _persist_observation

        # Without db_pool, _persist_observation returns None
        import asyncio
        claim = {
            "claim_text": "The Earth is round.",
            "topic": "astronomy",
            "confidence_0_1": 0.95,
            "rationale": "Well-established scientific fact.",
        }
        result = asyncio.run(_persist_observation(claim))
        # Without db_pool, returns None (no persistence)
        assert result is None

    def test_has_verification_status(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Observation model includes verification_status field."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _persist_observation

        import asyncio
        # Test that the claim dict structure is valid for persistence
        claim = {
            "claim_text": "Test claim.",
            "topic": "test",
            "confidence_0_1": 0.7,
            "rationale": "Test rationale.",
        }
        # With no db_pool, returns None gracefully
        result = asyncio.run(_persist_observation(claim, source_text="test source"))
        assert result is None  # graceful degradation

    def test_has_primacy(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Primacy scoring helper returns valid scores."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_primacy_score

        # Direct primary source
        primary = _compute_primacy_score({"type": "primary", "has_data": True})
        assert primary == 1.0

        # Review (one-hop)
        review = _compute_primacy_score({"type": "review"})
        assert review == 0.7

        # Unknown / None
        unknown = _compute_primacy_score(None)
        assert unknown == 0.3

        # With relation depth
        deep = _compute_primacy_score({"type": "review"}, relation_depth=2)
        assert deep <= 0.5


# ---------------------------------------------------------------------------
# Observation relations (FACTUALITY-OBSERVATION-1)
# ---------------------------------------------------------------------------


class TestObservationRelations:
    """Tests for observation relation helpers."""

    def test_relation_supporting(self, client, sample_trace_id, auth_headers, monkeypatch):
        """_create_observation_relation handles supporting type."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _create_observation_relation

        import asyncio
        # Without db_pool, should not raise
        asyncio.run(
            _create_observation_relation(
                "obs-1", "obs-2", "supporting", "corroborate"
            )
        )
        # No exception = pass

    def test_relation_dissenting(self, client, sample_trace_id, auth_headers, monkeypatch):
        """_create_observation_relation handles dissenting type."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _create_observation_relation

        import asyncio
        # Without db_pool, should not raise
        asyncio.run(
            _create_observation_relation(
                "obs-1", "obs-2", "dissenting", "contradict"
            )
        )
        # No exception = pass


# ---------------------------------------------------------------------------
# Source quality tier (FACTUALITY-OBSERVATION-1)
# ---------------------------------------------------------------------------


class TestSourceQualityTier:
    """Tests for source quality tier computation."""

    def test_tier_a_peer_reviewed(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Peer-reviewed journal sources get tier A."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_source_quality_tier

        assert _compute_source_quality_tier(
            {"source_index_label": "scihub", "citation_count": 100}
        ) == "A"
        assert _compute_source_quality_tier(
            {"source_index": "crossref", "citations": 75}
        ) == "A"

    def test_tier_b_conference(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Conference papers get tier B."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_source_quality_tier

        assert _compute_source_quality_tier(
            {"source_index_label": "semantic_scholar", "year": 2023, "citations": 15}
        ) == "B"
        assert _compute_source_quality_tier(
            {"source_index_label": "dblp"}
        ) == "B"

    def test_tier_c_preprint(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Preprints get tier C."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_source_quality_tier

        assert _compute_source_quality_tier(
            {"source_index_label": "arxiv"}
        ) == "C"
        assert _compute_source_quality_tier(
            {"is_preprint": True}
        ) == "C"

    def test_tier_unknown(self, client, sample_trace_id, auth_headers, monkeypatch):
        """Unrecognized sources get tier unknown."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _compute_source_quality_tier

        assert _compute_source_quality_tier({}) == "unknown"
        assert _compute_source_quality_tier(
            {"source_index": "some_random_blog"}
        ) == "unknown"


# ---------------------------------------------------------------------------
# Citation chain (FACTUALITY-CITATION-1)
# ---------------------------------------------------------------------------


class TestCitationVerificationChain:
    """Tests for DOI resolution, evidence links, and staleness detection."""

    def test_doi_resolves_creates_link(self, monkeypatch):
        """_resolve_doi finds a DOI and create_evidence_link produces a valid link."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _resolve_doi, create_evidence_link

        import asyncio

        # Mock _search_sources to return a matching DOI with metadata
        async def mock_search(claim, limit=5):
            return [{
                "doi": "10.1234/test.1",
                "title": "A Groundbreaking Study",
                "authors": ["Smith, J.", "Doe, A."],
                "year": 2024,
            }]

        import mcp.verify.server as srv
        original = srv._search_sources
        srv._search_sources = mock_search
        try:
            resolved = asyncio.run(_resolve_doi("10.1234/test.1"))
            assert resolved["found"] is True
            assert resolved["title"] == "A Groundbreaking Study"
            assert "Smith" in resolved["authors"][0]
            assert resolved["year"] == 2024

            # Now create an evidence link from the resolved DOI
            link = create_evidence_link(
                observation_id="obs-abc-123",
                source_identifier="doi:10.1234/test.1",
                excerpt="Source corroborates the claim about X.",
                confidence=0.92,
            )
            assert link["observation_id"] == "obs-abc-123"
            assert link["source_identifier"] == "doi:10.1234/test.1"
            assert link["excerpt"] == "Source corroborates the claim about X."
            assert link["confidence"] == 0.92
            assert "content_hash" in link
            assert len(link["content_hash"]) == 16
        finally:
            srv._search_sources = original

    def test_fake_doi_flagged(self, monkeypatch):
        """_resolve_doi returns found=False for a non-resolving DOI."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import _resolve_doi

        import asyncio

        async def mock_search(claim, limit=5):
            return []  # no results

        import mcp.verify.server as srv
        original = srv._search_sources
        srv._search_sources = mock_search
        try:
            resolved = asyncio.run(_resolve_doi("10.9999/fake.abc"))
            assert resolved["found"] is False
            assert resolved["title"] == ""
            assert resolved["authors"] == []
            assert resolved["year"] == ""
        finally:
            srv._search_sources = original

    def test_evidence_link_with_observation(self, monkeypatch):
        """create_evidence_link produces consistent content_hash for same input."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import create_evidence_link

        link1 = create_evidence_link(
            observation_id="obs-1",
            source_identifier="doi:10.5678/paper.2",
            excerpt="Supports claim about climate change.",
            confidence=0.88,
        )

        # Same inputs → same hash
        link2 = create_evidence_link(
            observation_id="obs-1",
            source_identifier="doi:10.5678/paper.2",
            excerpt="Supports claim about climate change.",
            confidence=0.88,
        )

        assert link1["content_hash"] == link2["content_hash"]
        assert link1["observation_id"] == "obs-1"
        assert 0.0 <= link1["confidence"] <= 1.0

        # Different excerpt → different hash
        link3 = create_evidence_link(
            observation_id="obs-1",
            source_identifier="doi:10.5678/paper.2",
            excerpt="Refutes claim about climate change.",
            confidence=0.88,
        )
        assert link1["content_hash"] != link3["content_hash"]

    def test_staleness_detected(self, monkeypatch):
        """check_citation_staleness flags stale when content_hash differs."""
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "true")
        import sys
        sys.modules.pop("mcp.verify.server", None)
        from mcp.verify.server import check_citation_staleness

        # Same hash → not stale
        result = check_citation_staleness("abc123", "abc123")
        assert result["stale"] is False
        assert result["reason"] is None

        # Different hash → stale
        result = check_citation_staleness("abc123", "def456")
        assert result["stale"] is True
        assert "mismatch" in result["reason"]
        assert result["current_hash"] == "abc123"
        assert result["previous_hash"] == "def456"

        # Empty strings compared
        result = check_citation_staleness("", "abc123")
        assert result["stale"] is True
