"""Tests for shadow-library adapter search self-provisioning (SAIMON-SHADOW-SELF-CLIENT-1).

LibGen + Anna's Archive adapters must create their own httpx client when none is
injected (matching Academic Torrents), so `search()` actually queries the source
instead of returning [] with "no HTTP client configured".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter

LIBGEN_HTML = """
<table class="c">
  <tr><th>id</th><th>authors</th><th>title</th><th>year</th><th>publisher</th>
      <th>edition</th><th>language</th><th>filetype</th></tr>
  <tr><td>abc123</td><td>Doe, Jane</td><td>Test Book</td><td>2020</td>
      <td>Pub</td><td>1</td><td>English</td><td>pdf</td></tr>
</table>
"""

ANNAS_HTML = """
<div class="search-result">
  <h3><a href="/md5/abc123">Test Paper</a></h3>
  <div class="authors"><span>Doe, Jane</span></div>
  <div class="year">2021</div>
  <div data-md5="abc123"></div>
  <div class="filetype">pdf</div>
</div>
"""


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    """Replaces httpx.AsyncClient for the self-provisioning path."""

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout
        self._text_by_url: dict[str, str] = {
            "https://libgen.li/index.php": LIBGEN_HTML,
            "https://annas-archive.gl/search": ANNAS_HTML,
        }

    async def post(self, url: str, data: Any = None, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(200, self._text_by_url.get(url, ""))

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        # Anna's Archive search URL includes a query string.
        base = url.split("?")[0]
        return FakeResponse(200, self._text_by_url.get(base, ""))

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize(
    "adapter_cls,query,expected_substr",
    [
        (LibGenAdapter, "test book", "Test Book"),
        (AnnasArchiveAdapter, "test paper", "Test Paper"),
    ],
)
def test_search_creates_own_client(monkeypatch, adapter_cls, query, expected_substr) -> None:
    """Adapter constructed with NO injected client still performs the search."""
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    async def _run() -> None:
        results = await adapter_cls().search(query, limit=5)
        assert results, f"{adapter_cls.__name__} returned no results without an injected client"
        assert any(expected_substr in r.title for r in results)

    asyncio.run(_run())


def test_libgen_no_client_is_not_empty_warning(monkeypatch) -> None:
    """Regression: search must not short-circuit on a missing client."""
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    async def _run() -> None:
        results = await LibGenAdapter().search("anything", limit=5)
        assert len(results) == 1

    asyncio.run(_run())
