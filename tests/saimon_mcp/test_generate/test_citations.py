"""Tests for SAIMON-GENERATE-CITATIONS-1 — generate citations + audit logging.

KPI-bound slice: moves `generate.grounded_rate` from its measured baseline
(0.00 — every generate call logs citations_count: 0) toward the signed-off
target (>= 0.80 by 2026-10-15).

Covers:
- generate_content returns populated citations when sources are given
- audit_log response entries carry citations_count (0 when no sources)
- generate_verified also populates citations from source material
"""

import json


class _FakeLLM:
    """Minimal LLM client for exercising the verified generation path."""

    async def generate(self, prompt: str) -> str:
        return "Synthesized content grounded in the provided sources."

    async def health_check(self) -> bool:
        return True


async def _no_claims(*args, **kwargs):
    """Monkeypatched verify-mcp extract: no claims (offline)."""
    return {"data": {"claims": []}}


async def _no_verify(*args, **kwargs):
    """Monkeypatched verify-mcp claim check: inconclusive (offline)."""
    return {
        "data": {
            "verifications": [],
            "overall_verdict": "inconclusive",
            "overall_confidence": 0.0,
        }
    }


def _response_events(capsys):
    """Parse the audit-log JSON lines printed to stdout, return 'response' events."""
    out = capsys.readouterr().out
    records = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return [r for r in records if r.get("event") == "response"]


def _generate_body(trace_id, *, sources=None):
    body = {
        "trace_id": trace_id,
        "content_type": "blog_post",
        "parameters": {"prompt": "Write about AI governance"},
    }
    if sources is not None:
        body["sources"] = sources
    return body


class TestGenerateCitations:
    def test_generate_content_with_sources_returns_citations(
        self, client, sample_trace_id, auth_headers
    ):
        """Response carries the provided source identifiers as citations."""
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(
                sample_trace_id,
                sources=[{"type": "knowledge_graph", "identifier": "kg-ai-concept"}],
            ),
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        citations = data.get("citations") or []
        assert "kg-ai-concept" in citations

    def test_generate_content_no_sources_logs_zero_citations(
        self, client, sample_trace_id, auth_headers, capsys
    ):
        """A generate call with no sources logs citations_count: 0 (honest)."""
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(sample_trace_id),
            headers=auth_headers,
        )
        assert response.status_code == 200
        events = _response_events(capsys)
        assert events, "expected an audit 'response' event"
        assert events[-1].get("citations_count") == 0

    def test_generate_content_with_sources_logs_citations_count(
        self, client, sample_trace_id, auth_headers, capsys
    ):
        """A generate call with sources logs citations_count > 0."""
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(
                sample_trace_id,
                sources=[
                    {"type": "knowledge_graph", "identifier": "kg-ai-concept"},
                    {"type": "web_page", "identifier": "https://example.com/a"},
                ],
            ),
            headers=auth_headers,
        )
        assert response.status_code == 200
        events = _response_events(capsys)
        assert events, "expected an audit 'response' event"
        assert events[-1].get("citations_count") == 2

    def test_generate_verified_with_sources_returns_citations(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """generate_verified also populates citations from source material."""
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())
        monkeypatch.setattr(server, "_call_verify_extract", _no_claims)
        monkeypatch.setattr(server, "_call_verify_claim", _no_verify)
        try:
            response = client.post(
                "/tools/generate_verified",
                json={
                    "trace_id": sample_trace_id,
                    "content_type": "research_note",
                    "parameters": {"prompt": "Explain the concept"},
                    "sources": [
                        {"type": "knowledge_graph", "identifier": "kg-node-42"}
                    ],
                },
                headers=auth_headers,
            )
        finally:
            server.set_llm_client(None)

        data = response.json()
        assert data["status"] == "success"
        citations = data.get("citations") or []
        assert "kg-node-42" in citations
