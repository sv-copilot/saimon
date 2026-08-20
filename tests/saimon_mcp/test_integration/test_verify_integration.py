"""Integration tests for verify-mcp — LLM backend wiring.

Verifies that verify-mcp can use an injected LLMClient for
fact-checking instead of placeholder verifications.
"""

from __future__ import annotations

import sys


def _fresh_verify_app(monkeypatch, api_key):
    """Reload the verify-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.verify.server", None)
    from saimon_mcp.verify.server import app
    return app


class TestLLMBackendInjection:
    """verify-mcp should support injecting an LLMClient for fact-checking."""

    def test_set_llm_client_function_exists(self):
        """Module has set_llm_client function."""
        sys.modules.pop("saimon_mcp.verify.server", None)
        from saimon_mcp.verify import server

        assert hasattr(server, "set_llm_client")
        assert callable(server.set_llm_client)

    def test_verify_claim_uses_llm_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_llm
    ):
        """When LLM is injected, verify_claim calls it for fact-checking."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.verify.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_llm.generate.return_value = (
            '{"verifications":[{"method":"source_corroboration","verdict":"supported",'
            '"confidence":0.85,"explanation":"Corroborated"}],"overall_verdict":"supported"}'
        )

        import saimon_mcp.verify.server as server_mod
        server_mod._llm_client = mock_llm
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verification",
                "parameters": {
                    "claim": "The sky is blue due to Rayleigh scattering.",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        mock_llm.generate.assert_called_once()

    def test_verify_claim_degraded_without_llm(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without LLM injected, verify_claim degrades gracefully."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.verify.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        from saimon_mcp.verify.server import app
        client = TestClient(app)

        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verification",
                "parameters": {"claim": "Test claim."},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
