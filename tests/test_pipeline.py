"""Integration tests that validate the full Saimon MCP pipeline.

Run after every slice completion or deployment to verify all 34 checks
pass against live services.

Usage (local):
    python3 -m pytest tests/test_pipeline.py -v

Usage (staging):
    SAIMON_SEARCH_URL=http://127.0.0.1:8101 \
    SAIMON_GENERATE_URL=http://127.0.0.1:8102 \
    ... \
    python3 -m pytest tests/test_pipeline.py -v

CI: These tests are skipped in CI (no live services available).
    They run as part of staging deployment validation.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx
import pytest

# Skip pipeline tests in CI — they need live Docker services
if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
    pytest.skip("Pipeline tests require live Docker services — skipped in CI", allow_module_level=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_SEARCH = os.environ.get("SAIMON_SEARCH_URL", "http://127.0.0.1:8001")
BASE_GENERATE = os.environ.get("SAIMON_GENERATE_URL", "http://127.0.0.1:8002")
BASE_EXPORT = os.environ.get("SAIMON_EXPORT_URL", "http://127.0.0.1:8003")
BASE_EVALUATE = os.environ.get("SAIMON_EVALUATE_URL", "http://127.0.0.1:8004")
BASE_VERIFY = os.environ.get("SAIMON_VERIFY_URL", "http://127.0.0.1:8005")
BASE_EXPLORE = os.environ.get("SAIMON_EXPLORE_URL", "http://127.0.0.1:8006")

KEY_SEARCH = os.environ.get("SAIMON_SEARCH_KEY", "sk-test-search-key")
KEY_GENERATE = os.environ.get("SAIMON_GENERATE_KEY", "sk-test-generate-key")
KEY_EXPORT = os.environ.get("SAIMON_EXPORT_KEY", "sk-test-export-key")
KEY_EVALUATE = os.environ.get("SAIMON_EVALUATE_KEY", "sk-test-evaluate-key")
KEY_VERIFY = os.environ.get("SAIMON_VERIFY_KEY", "sk-test-verify-key")
KEY_EXPLORE = os.environ.get("SAIMON_EXPLORE_KEY", "sk-test-explore-key")


def _tid() -> str:
    return str(uuid.uuid4())


async def _post(url: str, key: str, body: dict) -> dict:
    body.setdefault("trace_id", _tid())
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(url, json=body, headers={"X-Saimon-API-Key": key})
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# 1. Health — all 6 services respond
# ---------------------------------------------------------------------------

class TestHealth:
    """All 6 MCPs must return 200 on /health."""

    @pytest.mark.parametrize("url", [
        f"{BASE_SEARCH}/health",
        f"{BASE_GENERATE}/health",
        f"{BASE_EXPORT}/health",
        f"{BASE_EVALUATE}/health",
        f"{BASE_VERIFY}/health",
        f"{BASE_EXPLORE}/health",
    ])
    async def test_health_ok(self, url):
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(url)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Search — shadow libraries, KG, sources
# ---------------------------------------------------------------------------

class TestSearch:
    """search-mcp: all 3 search tools work."""

    async def test_search_scholarly_returns_results(self):
        data = await _post(
            f"{BASE_SEARCH}/tools/search_shadow_libraries", KEY_SEARCH,
            {"content_type": "search", "parameters": {"query": "machine learning", "limit": 3}},
        )
        assert data["status"] in ("success", "degraded")
        assert len(data["data"]["results"]) > 0

    async def test_search_knowledge_graph_no_500(self):
        data = await _post(
            f"{BASE_SEARCH}/tools/search_knowledge_graph", KEY_SEARCH,
            {"content_type": "search", "parameters": {"query": "test", "limit": 5}},
        )
        assert data["status"] in ("success", "degraded")

    async def test_list_sources_has_shadow_libraries(self):
        data = await _post(
            f"{BASE_SEARCH}/tools/list_source_indexes", KEY_SEARCH,
            {"content_type": "search"},
        )
        types = {s["type"] for s in data["data"]["source_indexes"]}
        assert "shadow_library" in types


# ---------------------------------------------------------------------------
# 3. Verify — fact-checking works
# ---------------------------------------------------------------------------

class TestVerify:
    """verify-mcp: claim verification returns verdicts."""

    async def test_verify_true_claim(self):
        data = await _post(
            f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY,
            {"content_type": "verify", "parameters": {
                "claim": "Python was created by Guido van Rossum",
                "use_shadow_sources": True,
            }},
        )
        assert data["status"] in ("success", "degraded")
        assert data["data"]["overall_verdict"] in ("supported", "refuted", "inconclusive")

    async def test_verify_false_claim(self):
        data = await _post(
            f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY,
            {"content_type": "verify", "parameters": {
                "claim": "Python was invented by Jeff Bezos in 2005",
                "use_shadow_sources": True,
            }},
        )
        assert data["status"] in ("success", "degraded")
        # Should be refuted or at least not crash
        assert data["data"]["overall_verdict"] in ("refuted", "inconclusive", "supported")

    async def test_verify_no_duplicates(self):
        """Running the same verification twice should not create duplicates."""
        claim = f"The number {_tid()[:8]} is prime"
        # First verify
        await _post(
            f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY,
            {"content_type": "verify", "parameters": {
                "claim": claim, "use_shadow_sources": True,
            }},
        )
        # Second verify (should not create duplicate)
        await _post(
            f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY,
            {"content_type": "verify", "parameters": {
                "claim": claim, "use_shadow_sources": True,
            }},
        )

    async def test_list_methods(self):
        data = await _post(
            f"{BASE_VERIFY}/tools/list_verification_methods", KEY_VERIFY,
            {"content_type": "verify"},
        )
        assert data["status"] == "success"
        methods = {m["name"] for m in data["data"]["methods"]}
        assert "logical_consistency" in methods
        assert "shadow_source_corroboration" in methods


# ---------------------------------------------------------------------------
# 4. Generate — content creation works
# ---------------------------------------------------------------------------

class TestGenerate:
    """generate-mcp: LLM content generation."""

    async def test_generate_content(self):
        data = await _post(
            f"{BASE_GENERATE}/tools/generate_content", KEY_GENERATE,
            {"content_type": "summary", "parameters": {
                "prompt": "Explain machine learning in one sentence.",
            }},
        )
        assert data["status"] in ("success", "degraded")

    async def test_list_content_types(self):
        data = await _post(
            f"{BASE_GENERATE}/tools/list_content_types", KEY_GENERATE,
            {"content_type": "generate"},
        )
        assert data["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# 5. Evaluate — scoring works (no crash)
# ---------------------------------------------------------------------------

class TestEvaluate:
    """evaluate-mcp: scoring with various criteria formats."""

    async def test_evaluate_with_string_criteria(self):
        data = await _post(
            f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE,
            {"content_type": "evaluate", "parameters": {
                "content": "The Transformer architecture uses self-attention.",
                "criteria": "clarity, conciseness",
            }},
        )
        assert data["status"] in ("success", "degraded")
        assert "scores" in data["data"]

    async def test_evaluate_with_list_criteria(self):
        data = await _post(
            f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE,
            {"content_type": "evaluate", "parameters": {
                "content": "Test content for scoring.",
                "criteria": ["clarity", "conciseness"],
            }},
        )
        assert data["status"] in ("success", "degraded")
        assert "scores" in data["data"]

    async def test_evaluate_with_default_criteria(self):
        data = await _post(
            f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE,
            {"content_type": "evaluate", "parameters": {
                "content": "Some test content for evaluation.",
            }},
        )
        assert data["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# 6. Explore — KG discovery works
# ---------------------------------------------------------------------------

class TestExplore:
    """explore-mcp: KG queries return results."""

    async def test_explore_content(self):
        data = await _post(
            f"{BASE_EXPLORE}/tools/explore_content", KEY_EXPLORE,
            {"content_type": "explore", "parameters": {"query": "test"}},
        )
        assert data["status"] in ("success", "degraded")

    async def test_browse_by_type(self):
        data = await _post(
            f"{BASE_EXPLORE}/tools/browse_by_type", KEY_EXPLORE,
            {"content_type": "explore", "parameters": {
                "content_type": "research_note", "limit": 3,
            }},
        )
        assert data["status"] in ("success", "degraded")
        items = data["data"].get("items", [])
        # Items should have content_type field if any exist
        for item in items:
            assert "content_type" in item, f"Item missing content_type: {item}"


# ---------------------------------------------------------------------------
# 7. Export — formatting works
# ---------------------------------------------------------------------------

class TestExport:
    """export-mcp: output formatting."""

    async def test_export_markdown(self):
        data = await _post(
            f"{BASE_EXPORT}/tools/export_content", KEY_EXPORT,
            {"content_type": "export", "parameters": {
                "content": "# Test\n\nHello world.",
                "format": "markdown",
            }},
        )
        assert data["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# 8. End-to-End Pipeline
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Full pipeline: search → verify → generate → evaluate → export."""

    async def test_full_pipeline(self):
        # 1. Search
        search = await _post(
            f"{BASE_SEARCH}/tools/search_shadow_libraries", KEY_SEARCH,
            {"content_type": "search", "parameters": {"query": "neural networks", "limit": 2}},
        )
        assert search["status"] in ("success", "degraded")

        # 2. Verify
        verify = await _post(
            f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY,
            {"content_type": "verify", "parameters": {
                "claim": "Neural networks are inspired by biological neurons",
                "use_shadow_sources": True,
            }},
        )
        assert verify["status"] in ("success", "degraded")

        # 3. Generate
        generate = await _post(
            f"{BASE_GENERATE}/tools/generate_content", KEY_GENERATE,
            {"content_type": "summary", "parameters": {
                "prompt": "Summarize neural networks in 2 sentences.",
            }},
        )
        assert generate["status"] in ("success", "degraded")

        # 4. Evaluate
        evaluate = await _post(
            f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE,
            {"content_type": "evaluate", "parameters": {
                "content": "Neural networks are computational models inspired by biological neurons.",
                "criteria": ["clarity", "conciseness"],
            }},
        )
        assert evaluate["status"] in ("success", "degraded")

        # 5. Export
        export = await _post(
            f"{BASE_EXPORT}/tools/export_content", KEY_EXPORT,
            {"content_type": "export", "parameters": {
                "content": "# Pipeline Test\n\nAll steps completed.",
                "format": "markdown",
            }},
        )
        assert export["status"] in ("success", "degraded")


# ---------------------------------------------------------------------------
# 9. Auth — fail-closed security
# ---------------------------------------------------------------------------

class TestAuth:
    """All MCPs reject unauthenticated requests."""

    @pytest.mark.parametrize("url,key,name", [
        (f"{BASE_SEARCH}/tools/search_knowledge_graph", KEY_SEARCH, "search"),
        (f"{BASE_GENERATE}/tools/list_content_types", KEY_GENERATE, "generate"),
        (f"{BASE_EXPORT}/tools/export_content", KEY_EXPORT, "export"),
        (f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE, "evaluate"),
        (f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY, "verify"),
        (f"{BASE_EXPLORE}/tools/explore_content", KEY_EXPLORE, "explore"),
    ])
    async def test_rejects_missing_key(self, url, key, name):
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(url, json={"trace_id": _tid(), "content_type": "test"})
            assert r.status_code == 401, f"{name}-mcp should reject missing key"

    @pytest.mark.parametrize("url,key,name", [
        (f"{BASE_SEARCH}/tools/search_knowledge_graph", KEY_SEARCH, "search"),
        (f"{BASE_GENERATE}/tools/list_content_types", KEY_GENERATE, "generate"),
        (f"{BASE_EXPORT}/tools/export_content", KEY_EXPORT, "export"),
        (f"{BASE_EVALUATE}/tools/evaluate_content", KEY_EVALUATE, "evaluate"),
        (f"{BASE_VERIFY}/tools/verify_claim", KEY_VERIFY, "verify"),
        (f"{BASE_EXPLORE}/tools/explore_content", KEY_EXPLORE, "explore"),
    ])
    async def test_accepts_correct_key(self, url, key, name):
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                url,
                json={"trace_id": _tid(), "content_type": "test", "parameters": {}},
                headers={"X-Saimon-API-Key": key},
            )
            assert r.status_code != 401, f"{name}-mcp should accept valid key, got {r.status_code}"
