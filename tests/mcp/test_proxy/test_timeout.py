"""Tests for the proxy _call_saimon timeout.

The composite tools (generate_verified, audit_content) run server-side
pipelines that take 30-75s. The proxy HTTP timeout must be >= 120s or
the proxy aborts before the server finishes (observed as an empty error).
"""

from __future__ import annotations

import importlib.util
import os
from unittest.mock import patch

import pytest


def _import_proxy_module():
    proxy_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "tools", "saimon-mcp-proxy", "proxy.py",
    )
    proxy_path = os.path.abspath(proxy_path)
    spec = importlib.util.spec_from_file_location("saimon_proxy_timeout", proxy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCallSaimonTimeout:
    """The proxy must allow composite pipelines to complete."""

    @pytest.mark.asyncio
    async def test_timeout_is_120_seconds(self):
        """_call_saimon constructs httpx.AsyncClient with timeout=120.0."""
        proxy = _import_proxy_module()
        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "success", "data": {}}

        class FakeClient:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def request(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(proxy.httpx, "AsyncClient", FakeClient):
            await proxy._call_saimon("saimon_list_sources", {})

        assert captured["kwargs"]["timeout"] == 120.0
