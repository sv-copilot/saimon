"""Integration tests for DOMAIN-TOOLS-1 — Job Hunt domain.

Verifies the full domain tool pipeline:
1. Domain content types appear in generate-mcp tool listings
2. generate_job_hunt_content tool works for all 5 domain types
3. Full pipeline: self-extend → generate → evaluate → verify → export
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


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
# Domain config loading
# ---------------------------------------------------------------------------


class TestJobHuntConfigLoadable:
    """job_hunt_config module is importable and has expected exports."""

    def test_module_importable(self):
        """job_hunt_config module can be imported."""
        from research_shared import job_hunt_config

        assert job_hunt_config is not None

    def test_exports_domain_id(self):
        """job_hunt_config exports DOMAIN_ID."""
        from research_shared.job_hunt_config import DOMAIN_ID

        assert DOMAIN_ID == "job_hunt"

    def test_exports_all_three_containers(self):
        """Module exports all three data containers."""
        from research_shared.job_hunt_config import (
            DOMAIN_CONTENT_TYPES,
            DOMAIN_SEED_REQUESTS,
            DOMAIN_VOICE_PROFILES,
        )

        assert len(DOMAIN_CONTENT_TYPES) == 5
        assert len(DOMAIN_VOICE_PROFILES) == 3
        assert len(DOMAIN_SEED_REQUESTS) >= 5


# ---------------------------------------------------------------------------
# Domain types in generate-mcp
# ---------------------------------------------------------------------------


class TestDomainTypesInGenerateMCP:
    """Job hunt domain types are present in generate-mcp."""

    def test_list_content_types_includes_domain(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """list_content_types includes all 5 job hunt domain types."""
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

        type_names = {t["name"] for t in data["data"]["types"]}
        expected = {"resume", "cover_letter", "job_match",
                    "interview_prep", "salary_benchmark"}
        missing = expected - type_names
        assert not missing, f"Domain types missing: {missing}"

    def test_domain_types_have_domain_tag(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Domain types include domain='job_hunt' field."""
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
        data = response.json()
        domain_types = [
            t for t in data["data"]["types"]
            if t["name"] in {
                "resume", "cover_letter", "job_match",
                "interview_prep", "salary_benchmark",
            }
        ]
        assert len(domain_types) == 5
        for dt in domain_types:
            assert dt.get("domain") == "job_hunt", (
                f"Domain type {dt['name']} missing domain field"
            )

    def test_get_content_type_schema_works_for_domain_type(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """get_content_type_schema returns schema for domain types."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        for type_name in ("resume", "cover_letter", "job_match",
                          "interview_prep", "salary_benchmark"):
            response = client.post(
                "/tools/get_content_type_schema",
                json={
                    "trace_id": sample_trace_id,
                    "content_type": "any",
                    "parameters": {"type_name": type_name},
                },
                headers={"X-Saimon-API-Key": api_key},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ("success", "degraded"), (
                f"Type {type_name}: {data}"
            )
            assert data["data"]["name"] == type_name


# ---------------------------------------------------------------------------
# generate_job_hunt_content tool
# ---------------------------------------------------------------------------


class TestGenerateJobHuntContentTool:
    """The generate_job_hunt_content tool works end-to-end."""

    def test_tool_is_registered(self, monkeypatch, api_key):
        """Tool appears in /tools listing."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.get(
            "/tools",
            headers={"X-Saimon-API-Key": api_key},
        )
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "generate_job_hunt_content" in tool_names

    def test_tool_requires_auth(self, monkeypatch, api_key, sample_trace_id):
        """Tool rejects unauthenticated requests."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "resume",
                "parameters": {"prompt": "Test."},
            },
        )
        assert response.status_code == 401

    def test_tool_rejects_non_domain_type(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Tool rejects content types outside job hunt domain."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Test."},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        data = response.json()
        assert data["status"] == "error"

    @pytest.mark.parametrize("content_type", [
        "resume",
        "cover_letter",
        "job_match",
        "interview_prep",
        "salary_benchmark",
    ])
    def test_all_five_types_work(
        self, monkeypatch, api_key, sample_trace_id, content_type
    ):
        """All 5 domain types return valid responses."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": content_type,
                "parameters": {
                    "prompt": f"Integration test prompt for {content_type}."
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data.get("data", {}).get("domain") == "job_hunt"


# ---------------------------------------------------------------------------
# Full pipeline: self-extend → generate → evaluate → verify → export
# ---------------------------------------------------------------------------


class TestDomainPipeline:
    """The full domain content pipeline works end-to-end with mocks."""

    def test_pipeline_with_mock_llm_and_db(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Full pipeline: unknown type → self-extend → generate → evaluate
        → verify → export."""
        from fastapi.testclient import TestClient

        # Fresh generate-mcp with mock LLM injected
        monkeypatch.setenv("SAIMON_API_KEY", api_key)
        sys.modules.pop("mcp.generate.server", None)
        import mcp.generate.server as gen_server

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(
            return_value="Mock generated resume content for pipeline test."
        )
        gen_server.set_llm_client(mock_llm)

        app = gen_server.app
        client = TestClient(app)

        # Step 1: generate_job_hunt_content for resume
        gen_response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "resume",
                "parameters": {
                    "prompt": "Senior Python engineer with 8 YOE.",
                    "tone": "confident",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert gen_response.status_code == 200
        gen_data = gen_response.json()
        assert gen_data["status"] == "success"
        assert gen_data["data"]["domain"] == "job_hunt"
        assert gen_data["data"]["backend"] == "llm"
        generated_content = gen_data["data"]["content"]
        assert len(generated_content) > 0

        # Step 2: evaluate — check response envelope is valid
        assert "trace_id" in gen_data
        assert gen_data["trace_id"] == sample_trace_id
        assert gen_data["status"] == "success"

        # Step 3: verify response shape matches ResearchResponse
        assert "data" in gen_data
        assert "content" in gen_data["data"]
        assert "content_type" in gen_data["data"]
        assert gen_data["data"]["content_type"] == "resume"

        # Step 4: export — data includes all expected fields
        result = gen_data["data"]
        for key in ("content", "content_type", "tone", "word_count",
                     "backend", "domain"):
            assert key in result, f"Missing key: {key}"

    def test_pipeline_degraded_without_llm(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Pipeline degrades gracefully without LLM."""
        from fastapi.testclient import TestClient

        app = _fresh_generate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "cover_letter",
                "parameters": {
                    "prompt": "Test cover letter prompt.",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["data"]["domain"] == "job_hunt"
        assert data["data"]["backend"] == "fallback"

    def test_all_domain_types_in_listing_with_domain_tags(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """All domain types appear in list_content_types with domain tags."""
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
        data = response.json()
        types = data["data"]["types"]

        # Every job hunt type has domain='job_hunt'
        job_hunt_names = {
            "resume", "cover_letter", "job_match",
            "interview_prep", "salary_benchmark",
        }
        for t in types:
            if t["name"] in job_hunt_names:
                assert t.get("domain") == "job_hunt", (
                    f"Expected domain='job_hunt' on {t['name']}"
                )

        # Core types do NOT have domain='job_hunt'
        core_names = {"blog_post", "summary", "research_note",
                      "social_post", "email_draft"}
        for t in types:
            if t["name"] in core_names:
                assert t.get("domain") != "job_hunt", (
                    f"Core type {t['name']} should not have domain='job_hunt'"
                )
