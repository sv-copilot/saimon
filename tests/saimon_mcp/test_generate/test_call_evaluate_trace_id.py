"""Tests for _call_evaluate trace_id — must be a valid UUID.

The ai-detect-loop previously sent a hardcoded trace_id "ai-detect-loop",
which the evaluate service rejects with a 422 (trace_id must be a UUID).
"""

import uuid as uuid_mod

import httpx
import pytest


class TestCallEvaluateTraceId:
    """_call_evaluate must send a valid UUID trace_id."""

    @pytest.mark.asyncio
    async def test_trace_id_is_valid_uuid(self, monkeypatch):
        captured: dict = {}

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": {"scores": []}}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                captured["json"] = json
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        import saimon_mcp.generate.server as server

        await server._call_evaluate("some generated content")

        trace_id = captured["json"]["trace_id"]
        uuid_mod.UUID(trace_id)  # raises ValueError if not a valid UUID
        assert trace_id != "ai-detect-loop"
