"""Tests for SAIMON-GROUNDING-BINDING-1 — mandatory claim→source binding.

KPI-bound slice: makes claim→source binding an invariant for every generated
content type and emits a `grounding` spectrum field
(`fully_cited` / `synthesis_informed` / `ungrounded`).

Covers:
- the centralized grounding classifier
- `grounding` field present on generated documents
- uncited-claim downgrade (never silently `fully_cited`)
- `grounding` level recorded in the generate audit log
"""

import json

from saimon_mcp.generate.server import classify_grounding

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _generate_body(trace_id, *, sources=None):
    body = {
        "trace_id": trace_id,
        "content_type": "blog_post",
        "parameters": {"prompt": "Write about AI governance"},
    }
    if sources is not None:
        body["sources"] = sources
    return body


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


class _FakeLLM:
    """Minimal LLM client for exercising the verified generation path."""

    async def generate(self, prompt: str) -> str:
        return "Claim one is supported by evidence. Claim two is a synthesis."

    async def health_check(self) -> bool:
        return True


async def _two_claims(*args, **kwargs):
    """Monkeypatched verify-mcp extract: two claims (offline)."""
    return {
        "data": {
            "claims": [
                {"claim_text": "Claim one is supported by evidence.",
                 "confidence_0_1": 0.9},
                {"claim_text": "Claim two is a synthesis.",
                 "confidence_0_1": 0.7},
            ]
        }
    }


async def _first_claim_cited_then_uncited(claim_text):
    """Monkeypatched verify-mcp claim check: cite the first claim only."""
    cited = claim_text == "Claim one is supported by evidence."
    verification = {
        "method": "shadow",
        "verdict": "supported" if cited else "inconclusive",
        "confidence": 0.9 if cited else 0.4,
        "explanation": "matched a source" if cited else "no source pointer",
    }
    if cited:
        verification["evidence_source"] = "doi:10.1000/grounded"
    return {
        "data": {
            "verifications": [verification],
            "overall_verdict": "supported" if cited else "inconclusive",
            "overall_confidence": 0.9 if cited else 0.4,
        }
    }


# ---------------------------------------------------------------------------
# Test 1: centralized grounding classifier
# ---------------------------------------------------------------------------

class TestClassifyGrounding:
    def test_no_sources_is_ungrounded(self):
        assert classify_grounding([]) == "ungrounded"
        assert classify_grounding(None) == "ungrounded"

    def test_sources_without_claim_extraction_is_synthesis_informed(self):
        # Direct generation is source-informed but not claim-bound, so it can
        # never be silently marked fully_cited.
        assert classify_grounding(["kg-ai-concept"]) == "synthesis_informed"

    def test_all_claims_cited_is_fully_cited(self):
        assert (
            classify_grounding(["kg-1"], total_claims=2, cited_claims=2)
            == "fully_cited"
        )

    def test_some_claims_cited_is_synthesis_informed(self):
        assert (
            classify_grounding(["kg-1"], total_claims=2, cited_claims=1)
            == "synthesis_informed"
        )

    def test_no_claims_cited_is_ungrounded(self):
        assert (
            classify_grounding(["kg-1"], total_claims=2, cited_claims=0)
            == "ungrounded"
        )

    def test_no_claims_extracted_is_ungrounded(self):
        assert (
            classify_grounding(["kg-1"], total_claims=0, cited_claims=0)
            == "ungrounded"
        )


# ---------------------------------------------------------------------------
# Test 2: grounding field present on generated documents
# ---------------------------------------------------------------------------

class TestGroundingFieldPresent:
    def test_generate_content_no_sources_emits_ungrounded(
        self, client, sample_trace_id, auth_headers
    ):
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(sample_trace_id),
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "grounding" in data["data"]
        assert data["data"]["grounding"] == "ungrounded"

    def test_generate_content_with_sources_is_synthesis_informed(
        self, client, sample_trace_id, auth_headers
    ):
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
        assert data["data"]["grounding"] == "synthesis_informed"

    def test_generate_verified_emits_grounding(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())
        monkeypatch.setattr(server, "_call_verify_extract", _two_claims)
        monkeypatch.setattr(
            server, "_call_verify_claim", _first_claim_cited_then_uncited
        )
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
        assert data["data"]["grounding"] in (
            "fully_cited",
            "synthesis_informed",
            "ungrounded",
        )




# ---------------------------------------------------------------------------
# Test 3: uncited-claim downgrade
# ---------------------------------------------------------------------------

class TestUncitedClaimDowngrade:
    def test_mixed_claims_never_fully_cited(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """A claim without a source pointer downgrades the document to
        synthesis_informed — never silently fully_cited."""
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())
        monkeypatch.setattr(server, "_call_verify_extract", _two_claims)
        monkeypatch.setattr(
            server, "_call_verify_claim", _first_claim_cited_then_uncited
        )
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
        assert data["data"]["grounding"] == "synthesis_informed"
        assert data["data"]["grounding"] != "fully_cited"

    def test_uncited_claim_has_no_citation_pointer(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """The unsourced claim is exposed without a citation pointer while the
        sourced claim carries one."""
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())
        monkeypatch.setattr(server, "_call_verify_extract", _two_claims)
        monkeypatch.setattr(
            server, "_call_verify_claim", _first_claim_cited_then_uncited
        )
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
        claims = data["data"].get("claims") or []
        by_text = {c["claim_text"]: c for c in claims}
        assert by_text["Claim one is supported by evidence."]["citation"] == "doi:10.1000/grounded"
        assert by_text["Claim one is supported by evidence."]["cited"] is True
        assert by_text["Claim two is a synthesis."]["citation"] is None
        assert by_text["Claim two is a synthesis."]["cited"] is False


# ---------------------------------------------------------------------------
# Test 4: audit log grounding level
# ---------------------------------------------------------------------------

class TestAuditLogGrounding:
    def test_no_sources_logs_ungrounded(
        self, client, sample_trace_id, auth_headers, capsys
    ):
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(sample_trace_id),
            headers=auth_headers,
        )
        assert response.status_code == 200
        events = _response_events(capsys)
        assert events, "expected an audit 'response' event"
        assert events[-1].get("grounding") == "ungrounded"
        assert events[-1].get("citations_count") == 0

    def test_with_sources_logs_synthesis_informed(
        self, client, sample_trace_id, auth_headers, capsys
    ):
        response = client.post(
            "/tools/generate_content",
            json=_generate_body(
                sample_trace_id,
                sources=[{"type": "knowledge_graph", "identifier": "kg-ai-concept"}],
            ),
            headers=auth_headers,
        )
        assert response.status_code == 200
        events = _response_events(capsys)
        assert events, "expected an audit 'response' event"
        assert events[-1].get("grounding") == "synthesis_informed"
        assert events[-1].get("citations_count") == 1

