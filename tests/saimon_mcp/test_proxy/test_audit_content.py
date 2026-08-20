"""Tests for saimon_audit_content composite pipeline (PIPELINE-AUDIT-1).

Tests the _run_audit_pipeline function with mocked
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


@pytest.fixture
def sample_audit_text() -> str:
    return (
        "AI is transforming software development through automated "
        "code generation and intelligent testing. Studies show that "
        "AI-assisted developers are 55% more productive. GitHub "
        "Copilot was launched by GitHub in 2021 and now has over "
        "1 million paying users."
    )


@pytest.fixture
def mock_audit_evaluate() -> dict[str, object]:
    """Mock evaluate_content response with ai_detection score."""
    return {
        "status": "success",
        "data": {
            "scores": [
                {"criterion": "template_phrases", "score": 0.3},
                {"criterion": "hedging", "score": 0.45},
                {"criterion": "burstiness", "score": 0.52},
            ],
            "overall_score": 0.42,
            "flags": ["template_phrases", "hedging_patterns"],
        },
    }


@pytest.fixture
def mock_audit_extract() -> dict[str, object]:
    """Mock extract_claims response with 2 claims."""
    return {
        "status": "success",
        "data": {
            "claims": [
                {
                    "claim_text": "AI-assisted developers are 55% more productive.",
                    "topic": "productivity",
                    "confidence_0_1": 0.9,
                },
                {
                    "claim_text": "GitHub Copilot was launched by GitHub in 2021.",
                    "topic": "GitHub Copilot",
                    "confidence_0_1": 0.95,
                },
            ],
            "count": 2,
        },
    }


@pytest.fixture
def mock_audit_verify() -> dict[str, object]:
    """Mock verify_claim response: one supported, one refuted."""
    return {
        "status": "success",
        "data": {
            "verifications": [
                {
                    "method": "source_corroboration",
                    "verdict": "inconclusive",
                    "confidence": 0.3,
                }
            ],
            "overall_verdict": "supported",
            "overall_confidence": 0.85,
            "methods_used": 1,
            "abstained": False,
            "evidence_links": [
                {"source_identifier": "doi:10.1234/ai.2023", "confidence": 0.85},
            ],
        },
    }


class TestAuditContent:
    """Unit tests for the audit_content composite pipeline."""

    @pytest.mark.asyncio
    async def test_happy_path_full_audit(
        self,
        sample_audit_text,
        mock_audit_evaluate,
        mock_audit_extract,
        mock_audit_verify,
    ):
        """Full pipeline: ai_detection → extract → verify each → report."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_audit_pipeline

        call_log: list[str] = []

        async def mock_call_saimon(tool_name, arguments):
            call_log.append(tool_name)
            if tool_name == "saimon_evaluate_content":
                return mock_audit_evaluate
            elif tool_name == "saimon_extract_claims":
                return mock_audit_extract
            elif tool_name == "saimon_verify_claim":
                return mock_audit_verify
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"content": sample_audit_text})

        assert result["status"] == "success"
        assert "saimon_evaluate_content" in call_log
        assert "saimon_extract_claims" in call_log
        assert "saimon_verify_claim" in call_log
        assert result["ai_detection"]["overall_score"] == 0.42
        assert result["claims"]["total"] == 2
        assert result["claims"]["verified"] == 2
        assert len(result["verifications"]) == 2
        assert len(result["evidence_links"]) == 2
        assert "2 claims extracted" in result["summary"]

    @pytest.mark.asyncio
    async def test_no_extractable_claims(
        self,
        sample_audit_text,
        mock_audit_evaluate,
    ):
        """Content with zero falsifiable claims → empty audit report."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_audit_pipeline

        extract_empty = {"status": "success", "data": {"claims": [], "count": 0}}

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_evaluate_content":
                return mock_audit_evaluate
            elif tool_name == "saimon_extract_claims":
                return extract_empty
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"content": sample_audit_text})

        assert result["status"] == "success"
        assert result["claims"]["total"] == 0
        assert result["claims"]["verified"] == 0
        assert len(result["verifications"]) == 0

    @pytest.mark.asyncio
    async def test_empty_content(self):
        """Empty text → error response immediately."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_audit_pipeline

        # Should return error without calling any service
        call_count = 0

        async def mock_call_saimon(tool_name, arguments):
            nonlocal call_count
            call_count += 1
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"content": ""})

        assert result["status"] == "error"
        assert "No content provided" in str(result.get("errors", []))
        assert call_count == 0, "no services should be called for empty content"

    @pytest.mark.asyncio
    async def test_ai_detection_degraded(
        self,
        sample_audit_text,
        mock_audit_extract,
        mock_audit_verify,
    ):
        """evaluate fails → continues without AI score, status degraded."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_audit_pipeline

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_evaluate_content":
                raise RuntimeError("evaluate unavailable")
            elif tool_name == "saimon_extract_claims":
                return mock_audit_extract
            elif tool_name == "saimon_verify_claim":
                return mock_audit_verify
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"content": sample_audit_text})

        assert result["status"] == "degraded"
        assert result["ai_detection"] is None
        assert result["claims"]["total"] == 2
        degraded = result.get("degraded_steps") or []
        assert any("ai_detection" in d for d in degraded)

    @pytest.mark.asyncio
    async def test_verify_failure_per_claim(
        self,
        sample_audit_text,
        mock_audit_evaluate,
        mock_audit_extract,
    ):
        """One verify call fails → that claim gets error verdict, others continue."""
        proxy = _import_proxy_module()
        pipeline = proxy._run_audit_pipeline

        call_count = 0

        async def mock_call_saimon(tool_name, arguments):
            nonlocal call_count
            if tool_name == "saimon_evaluate_content":
                return mock_audit_evaluate
            elif tool_name == "saimon_extract_claims":
                return mock_audit_extract
            elif tool_name == "saimon_verify_claim":
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("verify timeout")
                return {
                    "status": "success",
                    "data": {
                        "overall_verdict": "supported",
                        "overall_confidence": 0.9,
                        "abstained": False,
                        "verifications": [],
                        "evidence_links": [],
                    },
                }
            return {"status": "error"}

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await pipeline({"content": sample_audit_text})

        assert result["status"] == "degraded"
        assert len(result["verifications"]) == 2
        verdicts = [vc["verdict"] for vc in result["verifications"]]
        assert "error" in verdicts
        assert "supported" in verdicts
        degraded = result.get("degraded_steps") or []
        assert any("verify_claim" in d for d in degraded)

    @pytest.mark.asyncio
    async def test_format_audit_result(
        self,
        sample_audit_text,
        mock_audit_evaluate,
        mock_audit_extract,
        mock_audit_verify,
    ):
        """_format_audit_result produces readable output."""
        proxy = _import_proxy_module()
        formatter = proxy._format_audit_result

        data = {
            "status": "success",
            "ai_detection": {
                "overall_score": 0.42,
                "scores": [{"criterion": "template_phrases", "score": 0.3}],
                "flags": ["template_phrases"],
            },
            "claims": {"total": 2, "verified": 2, "unverified": 0, "disputed": 0},
            "verifications": [
                {
                    "claim_text": "AI-assisted developers are 55% more productive.",
                    "claim_index": 0,
                    "verdict": "supported",
                    "confidence": 0.85,
                },
                {
                    "claim_text": "GitHub Copilot was launched in 2021.",
                    "claim_index": 1,
                    "verdict": "supported",
                    "confidence": 0.92,
                },
            ],
            "evidence_links": [
                {"source_identifier": "doi:10.1234/ai.2023", "confidence": 0.85},
            ],
            "summary": "2 claims extracted. 2 supported.",
            "degraded_steps": None,
        }

        text = formatter(data)
        assert "SUCCESS" in text
        assert "AI Detection Score: 0.42" in text
        assert "POSSIBLY AI-ASSISTED" in text
        assert "2 claims extracted" in text
        assert "✅" in text
        assert "doi:10.1234/ai.2023" in text
