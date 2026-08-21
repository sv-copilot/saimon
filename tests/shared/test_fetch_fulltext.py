"""Tests for SourceIndexAdapter.fetch_fulltext across all 5 adapters.

SAIMON-FULLTEXT-RAG-1 (#97).  All HTTP is mocked — no network access.
"""

from __future__ import annotations

import pytest

from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter

ADAPTERS = [
    SciHubAdapter,
    InternetArchiveAdapter,
    LibGenAdapter,
    AnnasArchiveAdapter,
    AcademicTorrentsAdapter,
]


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


class TestSciHubFetch:
    async def test_returns_pdf_bytes(self) -> None:
        url = "https://sci-hub.ru/10.1000/example"
        client = FakeHttpClient({url: FakeResponse(200, b"%PDF-1.4 content")})
        adapter = SciHubAdapter(client)
        fetched = await adapter.fetch_fulltext(_result(doi="10.1000/example", download_url=url))
        assert fetched is not None
        assert fetched.data == b"%PDF-1.4 content"
        assert fetched.file_type == "pdf"

    async def test_html_wrapper_extracts_pdf_link(self) -> None:
        wrapper_url = "https://sci-hub.ru/10.1000/example"
        pdf_url = "https://example.com/file.pdf"
        html = f'<html><a href="{pdf_url}">download</a></html>'.encode()
        client = FakeHttpClient({
            wrapper_url: FakeResponse(200, html, headers={"content-type": "text/html"}),
            pdf_url: FakeResponse(200, b"%PDF-1.4 real"),
        })
        adapter = SciHubAdapter(client)
        fetched = await adapter.fetch_fulltext(_result(doi="10.1000/example", download_url=wrapper_url))
        assert fetched is not None
        assert fetched.data == b"%PDF-1.4 real"

    async def test_no_doi_returns_none(self) -> None:
        adapter = SciHubAdapter(FakeHttpClient())
        assert await adapter.fetch_fulltext(_result(doi=None)) is None

    async def test_network_error_fails_closed(self) -> None:
        adapter = SciHubAdapter(FakeHttpClient(error=ConnectionError("boom")))
        fetched = await adapter.fetch_fulltext(_result(doi="10.1000/example"))
        assert fetched is None

    async def test_non_200_fails_closed(self) -> None:
        adapter = SciHubAdapter(FakeHttpClient({}))
        fetched = await adapter.fetch_fulltext(_result(doi="10.1000/example"))
        assert fetched is None


# ---------------------------------------------------------------------------
# Internet Archive
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


class TestLibGenFetch:
    async def test_uses_md5_link(self) -> None:
        url = "https://libgen.li/ads.php?md5=abc123"
        client = FakeHttpClient({url: FakeResponse(200, b"book bytes")})
        adapter = LibGenAdapter(client)
        fetched = await adapter.fetch_fulltext(
            _result(identifier="md5:abc123", source_index="libgen", file_type="pdf")
        )
        assert fetched is not None
        assert fetched.data == b"book bytes"

    async def test_no_identifier_or_url_returns_none(self) -> None:
        adapter = LibGenAdapter(FakeHttpClient())
        fetched = await adapter.fetch_fulltext(_result(identifier="other", source_index="libgen"))
        assert fetched is None


# ---------------------------------------------------------------------------
# Anna's Archive
# ---------------------------------------------------------------------------


class TestAnnasArchiveFetch:
    async def test_requires_download_url(self) -> None:
        adapter = AnnasArchiveAdapter(FakeHttpClient())
        fetched = await adapter.fetch_fulltext(_result(source_index="annas_archive", download_url=None))
        assert fetched is None

    async def test_downloads_via_url(self) -> None:
        url = "https://annas-archive.gl/md5/abc123"
        client = FakeHttpClient({url: FakeResponse(200, b"paper bytes")})
        adapter = AnnasArchiveAdapter(client)
        fetched = await adapter.fetch_fulltext(_result(source_index="annas_archive", download_url=url))
        assert fetched is not None
        assert fetched.data == b"paper bytes"


# ---------------------------------------------------------------------------
# Academic Torrents
# ---------------------------------------------------------------------------


class TestAcademicTorrentsFetch:
    async def test_magnet_only_no_bytes(self) -> None:
        magnet = "magnet:?xt=urn:btih:deadbeef"
        adapter = AcademicTorrentsAdapter(FakeHttpClient())
        fetched = await adapter.fetch_fulltext(
            _result(source_index="academic_torrents", download_url=magnet)
        )
        assert fetched is not None
        assert fetched.data is None
        assert fetched.file_type == "torrent"
        assert fetched.download_url == magnet

    async def test_no_magnet_returns_none(self) -> None:
        adapter = AcademicTorrentsAdapter(FakeHttpClient())
        fetched = await adapter.fetch_fulltext(_result(source_index="academic_torrents", download_url=None))
        assert fetched is None
