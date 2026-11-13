"""Tests for SourceIndexAdapter.fetch_fulltext across all 5 adapters.

SAIMON-FULLTEXT-RAG-1 (#97).  All HTTP is mocked — no network access.
"""

from __future__ import annotations

import pytest

from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.internet_archive import InternetArchiveAdapter

ADAPTERS = [InternetArchiveAdapter]


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    async def aread(self) -> bytes:
        return self.content


class FakeHttpClient:
    """Minimal async HTTP client keyed by URL."""

    def __init__(self, responses: dict[str, FakeResponse] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or {}
        self.error = error
        self.calls: list[str] = []

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.responses.get(url, FakeResponse(status_code=404))


def _result(**kwargs) -> SourceSearchResult:
    defaults = {
        "type": "academic_paper",
        "identifier": "doi:10.1000/example",
        "doi": "10.1000/example",
        "title": "Example Paper",
        "source_index": "scihub",
        "source_index_label": "Sci-Hub",
    }
    defaults.update(kwargs)
    return SourceSearchResult(**defaults)


# ---------------------------------------------------------------------------
# protocol compliance
# ---------------------------------------------------------------------------


class TestProtocol:
    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    def test_fetch_fulltext_callable(self, adapter_cls) -> None:
        assert callable(adapter_cls().fetch_fulltext)


# ---------------------------------------------------------------------------
# Sci-Hub
# ---------------------------------------------------------------------------


class TestInternetArchiveFetch:
    async def test_returns_ocr_text(self) -> None:
        url = "https://archive.org/download/mybook/mybook_djvu.txt"
        client = FakeHttpClient({url: FakeResponse(200, b"OCR text body")})
        adapter = InternetArchiveAdapter(client)
        fetched = await adapter.fetch_fulltext(
            _result(identifier="ia:mybook", source_index="internet_archive")
        )
        assert fetched is not None
        assert fetched.data == b"OCR text body"
        assert fetched.file_type == "txt"

    async def test_missing_identifier_returns_none(self) -> None:
        adapter = InternetArchiveAdapter(FakeHttpClient())
        fetched = await adapter.fetch_fulltext(_result(identifier="ia:", source_index="internet_archive"))
        assert fetched is None


# ---------------------------------------------------------------------------
# LibGen
# ---------------------------------------------------------------------------


