"""Integration tests for evaluate-mcp — LLM backend wiring.

Verifies that evaluate-mcp can use an injected LLMClient for
quality scoring instead of heuristic placeholders.
"""

from __future__ import annotations

import sys


def _fresh_evaluate_app(monkeypatch, api_key):
    """Reload the evaluate-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("mcp.evaluate.server", None)
    from mcp.evaluate.server import app
    return app


class TestLLMBackendInjection:
    """evaluate-mcp should support injecting an LLMClient for scoring."""

    def test_set_llm_client_function_exists(self):
        """Module has set_llm_client function."""
        sys.modules.pop("mcp.evaluate.server", None)
        from mcp.evaluate import server

        assert hasattr(server, "set_llm_client")
        assert callable(server.set_llm_client)

    def test_evaluate_content_uses_llm_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_llm
    ):
        """When LLM is injected, evaluate_content calls it for scoring."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.evaluate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        # Return a JSON score from the mock
        mock_llm.generate.return_value = (
            '{"scores": [{"criterion":"clarity","score":0.85,"justification":"Clear"}],'
            '"overall_score": 0.85}'
        )

        import mcp.evaluate.server as server_mod
        server_mod._llm_client = mock_llm
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluation",
                "parameters": {
                    "content": "This is a test content for evaluation.",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify LLM was called
        mock_llm.generate.assert_called_once()

    def test_evaluate_content_degraded_without_llm(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without LLM injected, evaluate_content degrades gracefully."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.evaluate.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        from mcp.evaluate.server import app
        client = TestClient(app)

        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluation",
                "parameters": {"content": "Test content."},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_list_criteria_uses_seed_data(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """list_criteria returns criteria from seed_data.py."""
        from fastapi.testclient import TestClient

        app = _fresh_evaluate_app(monkeypatch, api_key)
        client = TestClient(app)

        response = client.post(
            "/tools/list_criteria",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluation",
                "parameters": {},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        criteria = data["data"]["criteria"]
        # Should have the core evaluation criteria
        names = {c["name"] for c in criteria}
        assert "clarity" in names
        assert "completeness" in names
        assert "coherence" in names
