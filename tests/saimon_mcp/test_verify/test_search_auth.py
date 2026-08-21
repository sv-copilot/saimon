"""Tests for the verify→search cross-service auth fix (SAIMON-VERIFY-SEARCH-AUTH-1, #197).

The bug: ``_search_sources`` sent verify-mcp's *own* ``SAIMON_API_KEY`` to
search-mcp, which rejects it with HTTP 401 → zero sources → verify abstains.
The fix introduces a dedicated ``SEARCH_API_KEY`` (mapped in compose to the
search service's key) and fails closed when it is missing or rejected.

These tests pin the fix:
1. ``_search_sources`` authenticates to search with ``SEARCH_API_KEY``.
2. A missing ``SEARCH_API_KEY`` fails closed and logs ``verify_search_auth_failed``.
3. A 401/403 rejection fails closed and logs ``verify_search_auth_failed``.
"""

from __future__ import annotations

from saimon_mcp.verify import server as verify_server


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in that captures request headers."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.captured_headers: dict[str, str] = {}
        self.captured_json: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, json=None, headers=None):
        self.captured_headers = headers or {}
        self.captured_json = json or {}
        return self._response


class TestSearchAuth:
    async def test_search_sources_uses_search_api_key(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test-search-key")
        response = _FakeResponse(200, {"data": {"results": [{"title": "Found Paper"}]}})
        fake = _FakeAsyncClient(response)
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources("a claim")

        assert results == [{"title": "Found Paper"}]
        assert fake.captured_headers.get("X-Saimon-API-Key") == "sk-test-search-key"

    async def test_missing_search_api_key_fails_closed(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)
        response = _FakeResponse(200, {"data": {"results": [{"title": "Found Paper"}]}})
        fake = _FakeAsyncClient(response)
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        with caplog.at_level("ERROR", logger="saimon.verify"):
            results = await verify_server._search_sources("a claim")

        assert results == []
        assert "verify_search_auth_failed" in caplog.text
        # fail-closed means no request is ever attempted without a key
        assert fake.captured_headers == {}

    async def test_auth_rejected_fails_closed(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test-search-key")
        fake = _FakeAsyncClient(_FakeResponse(401))
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        with caplog.at_level("ERROR", logger="saimon.verify"):
            results = await verify_server._search_sources("a claim")

        assert results == []
        assert "verify_search_auth_failed" in caplog.text
