"""Tests for verify shadow-search reliability (SAIMON-SEARCH-RELIABILITY-1, #201).

The bug: ``_search_sources`` swallowed every transport failure silently and
returned ``[]`` with no retry and no signal, so a transient search outage was
indistinguishable from "genuinely no sources".

The fix: retry once on transport errors (timeout/connect), log
``verify_search_degraded`` with reason and attempt, and never silently return
``[]`` without a logged reason.  Auth failures (401/403) are NOT retried.
"""

from __future__ import annotations

import httpx

from saimon_mcp.verify import server as verify_server


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _SequenceClient:
    """httpx.AsyncClient stand-in that raises/returns queued responses in order."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, json=None, headers=None):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class TestSearchSourcesRetriesOnTransportError:
    async def test_retries_once_then_returns_results(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        ok = _FakeResponse(200, {"data": {"results": [{"title": "Found Paper"}]}})
        fake = _SequenceClient([httpx.ReadTimeout("timeout"), ok])
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources("a claim")

        assert results == [{"title": "Found Paper"}]
        assert fake.calls == 2

    async def test_retries_connect_error(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        ok = _FakeResponse(200, {"data": {"results": [{"title": "Found Paper"}]}})
        fake = _SequenceClient([httpx.ConnectError("connect"), ok])
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources("a claim")

        assert results == [{"title": "Found Paper"}]
        assert fake.calls == 2

    async def test_auth_rejection_is_not_retried(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        fake = _SequenceClient([_FakeResponse(401)])
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources("a claim")

        assert results == []
        assert fake.calls == 1


class TestSearchSourcesLogsDegraded:
    async def test_logs_degraded_on_retry(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        ok = _FakeResponse(200, {"data": {"results": [{"title": "Found Paper"}]}})
        fake = _SequenceClient([httpx.ReadTimeout("timeout"), ok])
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        with caplog.at_level("WARNING", logger="saimon.verify"):
            results = await verify_server._search_sources("a claim")

        assert results == [{"title": "Found Paper"}]
        assert "verify_search_degraded" in caplog.text

    async def test_logs_degraded_when_retries_exhausted(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        fake = _SequenceClient(
            [httpx.ReadTimeout("timeout"), httpx.ReadTimeout("timeout")]
        )
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        with caplog.at_level("ERROR", logger="saimon.verify"):
            results = await verify_server._search_sources("a claim")

        assert results == []
        assert "verify_search_degraded" in caplog.text
