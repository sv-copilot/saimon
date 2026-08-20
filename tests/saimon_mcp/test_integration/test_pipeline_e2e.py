"""End-to-end integration test for the generate_verified pipeline.

Tests the full generate → evaluate → extract → verify → annotate chain
using FastAPI TestClients with mock LLM/DB injection, routing calls
through a mocked _call_saimon.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest


class TestEndToEndPipeline:
    """Integration test: full pipeline with live MCP servers."""

    @pytest.fixture(autouse=True)
    def _setup_mcps(self, mock_llm, mock_db, monkeypatch):
        """Set up each MCP with mock LLM/DB."""
        async def mock_generate(prompt):
            if "EXTRACT" in prompt or "extract" in prompt.lower():
                return (
                    '{"claims": ['
                    '{"claim_text": "Quantum entanglement was first described '
                    'by Einstein, Podolsky, and Rosen.", "topic": "EPR paradox", '
                    '"confidence_0_1": 0.95, '
                    '"rationale": "Historically verifiable publication."},'
                    '{"claim_text": "Entanglement has been demonstrated in '
                    'photons and electrons.", "topic": "experiments", '
                    '"confidence_0_1": 0.90, '
                    '"rationale": "Verifiable by published experiments."}'
                    ']}'
                )
            elif "VERIFY" in prompt or "verify" in prompt.lower():
                return (
                    '{"verifications": ['
                    '{"method": "source_corroboration", "verdict": "supported", '
                    '"confidence": 0.85, "explanation": "Confirmed.", '
                    '"evidence_source": "doi:10.1103/PhysRev.47.777"}'
                    '], "overall_verdict": "supported"}'
                )
            elif "REFUTE" in prompt or "refute" in prompt.lower():
                return (
                    '{"verifications": ['
                    '{"method": "adversarial_review", "verdict": "supported", '
                    '"confidence": 0.75, "explanation": "No flaws.", '
                    '"key_objections": []}'
                    '], "overall_verdict": "supported", "key_disagreements": []}'
                )
            else:
                return (
                    "Quantum entanglement was first described "
                    "by Einstein, Podolsky, and Rosen. "
                    "Entanglement has been demonstrated in "
                    "photons and electrons."
                )

        mock_llm.generate = AsyncMock(side_effect=mock_generate)
        mock_db.fetchrow = AsyncMock(return_value=None)
        mock_db.fetch = AsyncMock(return_value=[])

        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-integration-key")

        self.mock_llm = mock_llm
        self.mock_db = mock_db

    @pytest.mark.asyncio
    async def test_full_pipeline_end_to_end(self):
        """Full generate → evaluate → extract → verify → annotate chain."""
        from fastapi.testclient import TestClient

        from saimon_mcp.generate.server import app as gen_app
        from saimon_mcp.generate.server import set_llm_client as gen_set_llm
        from saimon_mcp.evaluate.server import app as eval_app
        from saimon_mcp.evaluate.server import set_llm_client as eval_set_llm
        from saimon_mcp.verify.server import app as verify_app
        from saimon_mcp.verify.server import (
            set_db_pool as verify_set_db,
            set_llm_client as verify_set_llm,
        )

        gen_set_llm(self.mock_llm)
        eval_set_llm(self.mock_llm)
        verify_set_llm(self.mock_llm)
        verify_set_db(self.mock_db)

        gen_client = TestClient(gen_app)
        eval_client = TestClient(eval_app)
        verify_client = TestClient(verify_app)
        auth = {"X-Saimon-API-Key": "sk-test-integration-key"}

        async def mock_call_saimon(tool_name, arguments):
            if tool_name == "saimon_generate_content":
                resp = gen_client.post("/tools/generate_content", json={
                    "trace_id": str(uuid.uuid4()),
                    "content_type": arguments.get("content_type", "research_note"),
                    "parameters": {
                        "prompt": arguments.get("prompt", ""),
                        "tone": arguments.get("tone", "neutral"),
                    },
                }, headers=auth)
                return resp.json()
            elif tool_name == "saimon_evaluate_content":
                resp = eval_client.post("/tools/evaluate_content", json={
                    "trace_id": str(uuid.uuid4()),
                    "content_type": "evaluate",
                    "parameters": {
                        "content": arguments.get("content", ""),
                        "criteria": arguments.get("criteria", "ai_detection"),
                    },
                }, headers=auth)
                return resp.json()
            elif tool_name == "saimon_extract_claims":
                resp = verify_client.post("/tools/extract_claims", json={
                    "trace_id": str(uuid.uuid4()),
                    "content_type": "extract",
                    "parameters": {
                        "source_text": arguments.get("source_text", ""),
                        "max_claims": arguments.get("max_claims", 5),
                    },
                }, headers=auth)
                return resp.json()
            elif tool_name == "saimon_verify_claim":
                resp = verify_client.post("/tools/verify_claim", json={
                    "trace_id": str(uuid.uuid4()),
                    "content_type": "verify",
                    "parameters": {
                        "claim": arguments.get("claim", ""),
                        "adversarial": arguments.get("adversarial", True),
                        "risk_profile": arguments.get("risk_profile", "high"),
                        "verify_citations": arguments.get("verify_citations", True),
                        "use_shadow_sources": arguments.get("use_shadow_sources", True),
                    },
                }, headers=auth)
                return resp.json()
            return {"status": "error", "errors": [f"Unknown: {tool_name}"]}

        proxy_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "tools", "saimon-mcp-proxy", "proxy.py",
        )
        proxy_path = os.path.abspath(proxy_path)
        spec = importlib.util.spec_from_file_location("saimon_proxy_int", proxy_path)
        proxy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proxy)

        with patch.object(proxy, "_call_saimon", side_effect=mock_call_saimon):
            result = await proxy._run_generate_verified_pipeline({
                "prompt": "Explain quantum entanglement",
                "content_type": "research_note",
                "tone": "neutral",
                "ai_detection": True,
            })

        assert result["status"] in ("success", "degraded"), (
            f"Status: {result['status']}, "
            f"errors: {result.get('errors', '')}, "
            f"degraded: {result.get('degraded_steps', '')}"
        )
        assert "content" in result
        assert "verification_summary" in result
        vs = result["verification_summary"]
        assert "total_claims" in vs
        assert "supported" in vs
        assert "verified_claims" in vs
