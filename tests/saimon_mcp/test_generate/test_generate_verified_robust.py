"""Tests for SAIMON-GENERATE-VERIFIED-ROBUST-1 (#212).

Covers the three acceptance criteria:

1. Induced disconnect → one retry → same annotated output as the clean path.
2. Manual fallback produces identical ``[VERIFIED ✓]`` / ``[UNVERIFIED ⚠]`` markers.
3. ``generate_verified_fallback`` is logged on degradation and absent on clean runs.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

# ---------------------------------------------------------------------------
# shared mocks
# ---------------------------------------------------------------------------

CLEAN_CONTENT = (
    "Claim one is supported by evidence. "
    "Claim two is a synthesis."
)

FALLBACK_CONTENT = (
    "The fallback claim is supported by a source. "
    "The fallback claim is refuted by a source."
)


class _FakeLLM:
    """Minimal LLM client so the endpoint passes its ``_llm_client`` guard."""

    async def generate(self, prompt: str) -> str:
        return CLEAN_CONTENT

    async def health_check(self) -> bool:
        return True


async def _clean_extract(*args, **kwargs):
    return {
        "data": {
            "claims": [
                {"claim_text": "Claim one is supported by evidence."},
                {"claim_text": "Claim two is a synthesis."},
            ]
        }
    }


async def _clean_verify(claim_text: str):
    supported = claim_text == "Claim one is supported by evidence."
    verdict = "supported" if supported else "inconclusive"
    verification = {"verdict": verdict}
    if supported:
        verification["evidence_source"] = "doi:10.1000/grounded"
    return {
        "data": {
            "verifications": [verification],
            "overall_verdict": verdict,
        }
    }


async def _fallback_extract(*args, **kwargs):
    return {
        "data": {
            "claims": [
                {"claim_text": "The fallback claim is supported by a source."},
                {"claim_text": "The fallback claim is refuted by a source."},
            ]
        }
    }


async def _fallback_verify(claim_text: str):
    verdict = (
        "supported" if "supported by a source" in claim_text else "refuted"
    )
    return {
        "data": {
            "verifications": [{"verdict": verdict}],
            "overall_verdict": verdict,
        }
    }


def _audit_events(capsys):
    """Parse JSON-line audit output printed to stdout."""
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
    return records


# ---------------------------------------------------------------------------
# 1. Retry-once on disconnect
# ---------------------------------------------------------------------------

class TestRetryOnceOnDisconnect:
    @pytest.mark.asyncio
    async def test_fast_path_retries_once_on_transport_error(self, monkeypatch):
        """A single disconnect is retried, producing the clean annotated output."""
        from saimon_mcp.generate import server

        calls: list[bool] = []

        async def flaky_generate(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            calls.append(skip_critique)
            if len(calls) == 1:
                raise ConnectionError("server disconnected")
            return CLEAN_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", flaky_generate)

        result = await server._generate_verified_fast(
            "prompt", "research_note", "neutral", None, None
        )

        assert result == CLEAN_CONTENT
        assert len(calls) == 2, "transport error should trigger exactly one retry"

    @pytest.mark.asyncio
    async def test_non_transport_error_does_not_retry(self, monkeypatch):
        """Non-transport LLM errors propagate without a retry."""
        from research_shared.llm import LLMError
        from saimon_mcp.generate import server

        calls = 0

        async def failing_generate(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            nonlocal calls
            calls += 1
            raise LLMError("bad prompt", code="GENERATION_ERROR")

        monkeypatch.setattr(server, "_generate_via_llm", failing_generate)

        with pytest.raises(LLMError):
            await server._generate_verified_fast(
                "prompt", "research_note", "neutral", None, None
            )

        assert calls == 1



# ---------------------------------------------------------------------------
# 2. Manual fallback chain equivalence
# ---------------------------------------------------------------------------

class TestFallbackChainEquivalence:
    @pytest.mark.asyncio
    async def test_manual_chain_emits_identical_markers(self, monkeypatch):
        """Fallback annotates content with [VERIFIED ✓] / [UNVERIFIED ⚠ ...]."""
        from saimon_mcp.generate import server

        async def plain_generate(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            assert skip_critique is True
            return FALLBACK_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", plain_generate)
        monkeypatch.setattr(server, "_call_verify_extract", _fallback_extract)
        monkeypatch.setattr(server, "_call_verify_claim", _fallback_verify)

        annotated, verification = await server._generate_verified_manual_chain(
            "prompt", "research_note", "neutral", None, None
        )

        assert "[VERIFIED ✓]" in annotated
        assert "[UNVERIFIED ⚠ refuted]" in annotated
        # verification results are still available for DB persistence
        assert verification["claims_extracted"] == 2

    @pytest.mark.asyncio
    async def test_clean_and_fallback_paths_share_annotator(self, monkeypatch):
        """Both paths use _annotate_content, so markers are identical."""
        from saimon_mcp.generate import server

        bindings = [
            {"claim_text": "A.", "verdict": "supported"},
            {"claim_text": "B.", "verdict": "refuted"},
            {"claim_text": "C.", "verdict": "inconclusive"},
        ]
        annotated = server._annotate_content("A. B. C.", bindings)

        assert "[VERIFIED ✓] A." in annotated
        assert "[UNVERIFIED ⚠ refuted] B." in annotated
        assert "[UNVERIFIED ⚠ inconclusive] C." in annotated



# ---------------------------------------------------------------------------
# 3. Fallback audit field
# ---------------------------------------------------------------------------

class TestFallbackAuditField:
    @pytest.mark.asyncio
    async def test_resilient_clean_run_has_no_fallback(self, monkeypatch):
        """Clean generation produces no fallback info and no fallback log."""
        from saimon_mcp.generate import server

        logger = Mock()

        async def ok_generate(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            return CLEAN_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", ok_generate)
        monkeypatch.setattr(server, "_call_verify_extract", _clean_extract)
        monkeypatch.setattr(server, "_call_verify_claim", _clean_verify)

        content, _verification, fallback_info = await server._generate_verified_resilient(
            "prompt", "research_note", "neutral", None, None, logger
        )

        assert fallback_info is None
        assert "[VERIFIED ✓]" in content
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_resilient_transport_error_logs_fallback(self, monkeypatch):
        """A transport error after retry logs generate_verified_fallback."""
        from saimon_mcp.generate import server

        logger = Mock()

        async def disconnect_then_plain(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            if not skip_critique:
                raise ConnectionError("server disconnected")
            return FALLBACK_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", disconnect_then_plain)
        monkeypatch.setattr(server, "_call_verify_extract", _fallback_extract)
        monkeypatch.setattr(server, "_call_verify_claim", _fallback_verify)

        content, _verification, fallback_info = await server._generate_verified_resilient(
            "prompt", "research_note", "neutral", None, None, logger
        )

        assert fallback_info is not None
        assert fallback_info["attempt"] == 2
        assert "server disconnected" in fallback_info["reason"]
        assert "[VERIFIED ✓]" in content

        logger.warning.assert_called_once()
        args, kwargs = logger.warning.call_args
        assert args[0] == "generate_verified_fallback"
        assert kwargs.get("attempt") == 2
        assert "server disconnected" in kwargs.get("reason", "")



    def test_endpoint_audit_field_absent_on_clean_run(
        self, client, sample_trace_id, auth_headers, monkeypatch, capsys
    ):
        """The audit payload has no fallback marker on a clean run."""
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())

        async def ok_generate(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            return CLEAN_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", ok_generate)
        monkeypatch.setattr(server, "_call_verify_extract", _clean_extract)
        monkeypatch.setattr(server, "_call_verify_claim", _clean_verify)

        try:
            response = client.post(
                "/tools/generate_verified",
                json={
                    "trace_id": sample_trace_id,
                    "content_type": "research_note",
                    "parameters": {"prompt": "Explain the concept"},
                },
                headers=auth_headers,
            )
        finally:
            server.set_llm_client(None)

        data = response.json()
        assert data["status"] == "success"
        assert "generate_verified_fallback" not in data["data"]

        events = _audit_events(capsys)
        assert not any(e.get("event") == "generate_verified_fallback" for e in events)
        responses = [e for e in events if e.get("event") == "response"]
        assert responses, "expected an audit response event"
        assert responses[-1].get("generate_verified_fallback") is False



    def test_endpoint_audit_field_present_on_fallback(
        self, client, sample_trace_id, auth_headers, monkeypatch, capsys
    ):
        """The audit payload marks a degraded run via generate_verified_fallback."""
        from saimon_mcp.generate import server

        server.set_llm_client(_FakeLLM())

        async def disconnect_then_plain(
            prompt, content_type, tone, ct_schema, sources=None, skip_critique=True
        ):
            if not skip_critique:
                raise ConnectionError("server disconnected")
            return FALLBACK_CONTENT

        monkeypatch.setattr(server, "_generate_via_llm", disconnect_then_plain)
        monkeypatch.setattr(server, "_call_verify_extract", _fallback_extract)
        monkeypatch.setattr(server, "_call_verify_claim", _fallback_verify)

        try:
            response = client.post(
                "/tools/generate_verified",
                json={
                    "trace_id": sample_trace_id,
                    "content_type": "research_note",
                    "parameters": {"prompt": "Explain the concept"},
                },
                headers=auth_headers,
            )
        finally:
            server.set_llm_client(None)

        data = response.json()
        assert data["status"] == "success"
        fallback = data["data"].get("generate_verified_fallback")
        assert fallback is not None
        assert fallback["attempt"] == 2

        events = _audit_events(capsys)
        fallback_events = [
            e for e in events if e.get("event") == "generate_verified_fallback"
        ]
        assert fallback_events, "expected a generate_verified_fallback audit event"
        assert fallback_events[0].get("attempt") == 2
        assert "server disconnected" in fallback_events[0].get("reason", "")

        responses = [e for e in events if e.get("event") == "response"]
        assert responses, "expected an audit response event"
        assert responses[-1].get("generate_verified_fallback") is True

