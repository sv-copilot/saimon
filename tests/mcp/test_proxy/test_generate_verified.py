"""Tests for saimon_generate_verified composite pipeline.

Tests the _run_generate_verified_pipeline function with mocked
httpx calls to the underlying MCP services.
"""

from __future__ import annotations

import importlib.util
import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_proxy_module():
    """Import proxy.py from the hyphenated directory via importlib."""
    proxy_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "tools", "saimon-mcp-proxy", "proxy.py",
    )
    proxy_path = os.path.abspath(proxy_path)
    spec = importlib.util.spec_from_file_location("saimon_proxy", proxy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGenerateVerified:
    """Unit tests for the generate_verified composite pipeline."""

    # ── Test 1: Happy path ──────────────────────────────────────
    @pytest.mark.asyncio
    async def test_happy_path_full_pipeline(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
    ):
        """Full pipeline: generate → extract → verify each claim → annotate."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        call_count = 0

        async def mock_call_saimon(tool_name, arguments):
            nonlocal call_count
            call_count += 1
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error", "errors": ["unknown tool"]}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "content_type": "research_note",
                "tone": "neutral",
            })

        assert result["status"] == "success"
        assert "[VERIFIED ✓]" in result["content"]
        vs = result["verification_summary"]
        assert vs["total_claims"] == 3
        assert vs["supported"] == 3
        assert vs["refuted"] == 0
        assert vs["inconclusive"] == 0
        assert vs["errors"] == 0
        assert result["degraded_steps"] is None
        assert call_count == 5

    # ── Test 2: No claims found ─────────────────────────────────
    @pytest.mark.asyncio
    async def test_no_claims_found(
        self,
        sample_prompt,
        mock_generated_content,
    ):
        """When extract_claims returns no claims, pipeline completes gracefully."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {"status": "success", "data": {"claims": [], "count": 0}}

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"prompt": sample_prompt})

        assert result["status"] == "success"
        assert result["content"] == mock_generated_content
        vs = result["verification_summary"]
        assert vs["total_claims"] == 0
        assert vs["supported"] == 0
        assert result["evidence_links"] == []
        assert result["degraded_steps"] is None

    # ── Test 3: Verify failure degrades gracefully ──────────────
    @pytest.mark.asyncio
    async def test_verify_failure_degrades(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
    ):
        """When one verify_claim call fails, others continue and step is degraded."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                claim = arguments.get("claim", "")
                if "Aspect" in claim:
                    raise RuntimeError("verify service timeout")
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"prompt": sample_prompt})

        assert result["status"] == "degraded"
        vs = result["verification_summary"]
        assert vs["total_claims"] == 3
        assert vs["supported"] == 2
        assert vs["errors"] == 1
        degraded = result["degraded_steps"] or []
        assert any("verify_claim" in d for d in degraded)
        assert "[VERIFIED ✓]" in result["content"]

    # ── Test 4: Extract claims failure degrades ─────────────────
    @pytest.mark.asyncio
    async def test_extract_claims_failure_degrades(
        self,
        sample_prompt,
        mock_generated_content,
    ):
        """When extract_claims fails, pipeline still returns generated content."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                raise RuntimeError("extract service unavailable")
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"prompt": sample_prompt})

        assert result["status"] == "degraded"
        assert result["content"] == mock_generated_content
        vs = result["verification_summary"]
        assert vs["total_claims"] == 0
        degraded = result["degraded_steps"] or []
        assert any("extract_claims" in d for d in degraded)

    # ── Test 5: Full chain with ai_detection ────────────────────
    @pytest.mark.asyncio
    async def test_full_chain_with_ai_detection(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
        mock_evaluate_ai_detection,
    ):
        """Pipeline with ai_detection=true includes AI detection score."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        call_log: list[str] = []

        async def mock_call_saimon(tool_name, arguments):
            call_log.append(tool_name)
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_evaluate_content":
                return mock_evaluate_ai_detection
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "ai_detection": True,
            })

        assert result["status"] == "success"
        assert result["ai_detection_score"] is not None
        ai_score = result["ai_detection_score"]
        assert ai_score["overall_score"] == 0.65
        assert len(ai_score["scores"]) == 1
        assert ai_score["scores"][0]["criterion"] == "ai_detection"
        assert "saimon_evaluate_content" in call_log
        assert "[VERIFIED ✓]" in result["content"]

    # ── Test 6: AI detection failure degrades but continues ─────
    @pytest.mark.asyncio
    async def test_ai_detection_failure_degrades_but_continues(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
    ):
        """When evaluate_content fails, pipeline continues without AI score."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_evaluate_content":
                raise RuntimeError("evaluate service unavailable")
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "ai_detection": True,
            })

        assert result["status"] == "degraded"
        assert result["ai_detection_score"] is None
        assert "[VERIFIED ✓]" in result["content"]
        assert result["verification_summary"]["total_claims"] == 3
        degraded = result["degraded_steps"] or []
        assert any("ai_detection" in d for d in degraded)


class TestAutoSearch:
    """Unit tests for the auto_search feature (PIPELINE-AUTOSEARCH-1)."""

    @pytest.mark.asyncio
    async def test_auto_search_discovers_sources(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
        mock_search_results,
    ):
        """When auto_search: true, search is called and results are fed as sources."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        call_log: list[str] = []

        async def mock_call_saimon(tool_name, arguments):
            call_log.append(tool_name)
            if tool_name == "saimon_search_scholarly":
                return mock_search_results
            elif tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "auto_search": True,
            })

        assert result["status"] == "success"
        assert "saimon_search_scholarly" in call_log, "auto_search should call search"
        # Search should be called before generate
        search_idx = call_log.index("saimon_search_scholarly")
        gen_idx = call_log.index("saimon_generate_content")
        assert search_idx < gen_idx, "search must happen before generate"

    @pytest.mark.asyncio
    async def test_auto_search_graceful_on_search_failure(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
    ):
        """When search fails, pipeline continues without sources (graceful degradation)."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_search_scholarly":
                raise RuntimeError("search unavailable")
            elif tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "auto_search": True,
            })

        assert result["status"] == "degraded"
        assert "[VERIFIED ✓]" in result["content"]
        degraded = result.get("degraded_steps") or []
        assert any("auto_search" in d for d in degraded)

    @pytest.mark.asyncio
    async def test_auto_search_false_preserves_manual_sources(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
    ):
        """When auto_search is false (default), search is NOT called."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        call_log: list[str] = []

        async def mock_call_saimon(tool_name, arguments):
            call_log.append(tool_name)
            if tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "sources": [{"type": "manual", "identifier": "custom-source"}],
            })

        assert result["status"] == "success"
        assert "saimon_search_scholarly" not in call_log, (
            "search should not be called when auto_search is false"
        )

    @pytest.mark.asyncio
    async def test_auto_search_empty_results_no_error(
        self,
        sample_prompt,
        mock_generated_content,
        mock_extracted_claims,
        mock_verify_supported,
        mock_search_empty,
    ):
        """When search returns no results, pipeline continues without degraded step."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_generate_verified_pipeline

        gen_data = {"status": "success", "data": {"content": mock_generated_content}}
        extract_data = {
            "status": "success",
            "data": {"claims": mock_extracted_claims, "count": len(mock_extracted_claims)},
        }

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_search_scholarly":
                return mock_search_empty
            elif tool_name == "saimon_generate_content":
                return gen_data
            elif tool_name == "saimon_extract_claims":
                return extract_data
            elif tool_name == "saimon_verify_claim":
                return mock_verify_supported
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({
                "prompt": sample_prompt,
                "auto_search": True,
            })

        assert result["status"] == "success"
        # Empty results should NOT produce a degraded step (not an error)
        degraded = result.get("degraded_steps")
        if degraded:
            assert not any("auto_search" in d for d in degraded)
