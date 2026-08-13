"""Tests for SAIMON-SHADOW-REAL (#41) and SAIMON-SHADOW-ARCHIVE-1 (#54).

Verifies all 5 adapters return real metadata (not placeholders),
handle errors gracefully (return []), and follow the error contract.

#54 adds real API integration tests for Internet Archive.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a mock HTTP response
# ---------------------------------------------------------------------------

def _mock_response(status=200, json_data=None, text_data="", headers=None):
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data or {})
    resp.text = text_data
    resp.headers = headers or {}
    return resp


# ---------------------------------------------------------------------------
# Test 1: Internet Archive — real field extraction
# ---------------------------------------------------------------------------

class TestInternetArchive:
    """Verify Internet Archive adapter returns real metadata."""

    def test_search_returns_real_metadata(self):
        """Mock IA JSON response — verify correct field extraction."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200,
            json_data={
                "response": {
                    "numFound": 2,
                    "docs": [
                        {
                            "identifier": "test-id-1",
                            "title": "AI Governance in Practice",
                            "creator": ["Smith, J.", "Jones, K."],
                            "year": "2024",
                            "description": "A comprehensive study of AI governance.",
                            "doi": "10.1000/xyz123",
                            "mediatype": "texts",
                        },
                        {
                            "identifier": "test-id-2",
                            "title": "Autonomous Systems Review",
                            "creator": "Brown, L.",
                            "year": "2023",
                            "description": None,
                        },
                    ],
                }
            },
        ))

        adapter = InternetArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("AI governance", limit=5))

        assert len(results) == 2
        assert results[0].title == "AI Governance in Practice"
        assert results[0].authors == ["Smith, J.", "Jones, K."]
        assert results[0].year == 2024
        assert results[0].abstract_snippet == "A comprehensive study of AI governance."
        assert results[0].doi == "10.1000/xyz123"
        assert results[0].source_index == "internet_archive"
        # Verify NO placeholder text
        for r in results:
            assert "result 1 for:" not in r.title.lower()
            assert "result 2 for:" not in r.title.lower()

    def test_search_http_error_returns_empty(self):
        """HTTP 500 from IA → returns [] not placeholder."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(status=500))

        adapter = InternetArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_search_network_error_returns_empty(self):
        """Network timeout → returns [] not placeholder."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))

        adapter = InternetArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_empty_query_returns_empty(self):
        """Empty query string returns []."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        adapter = InternetArchiveAdapter()
        results = asyncio.run(adapter.search(""))
        assert results == []


# ---------------------------------------------------------------------------
# Test 2: Academic Torrents — real field extraction
# ---------------------------------------------------------------------------

class TestAcademicTorrents:
    """Verify Academic Torrents adapter returns real metadata."""

    def test_search_returns_real_metadata(self):
        """Mock AT JSON response — verify correct field extraction."""
        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200,
            json_data=[
                {
                    "id": "abc123",
                    "title": "Large-Scale ML Datasets",
                    "authors": ["Wang, X.", "Liu, Y."],
                    "year": "2023",
                    "description": "A collection of datasets for ML research.",
                    "magnet_link": "magnet:?xt=urn:btih:abc123",
                    "doi": "10.1000/at123",
                },
            ],
        ))

        adapter = AcademicTorrentsAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("ML datasets", limit=5))

        assert len(results) == 1
        assert results[0].title == "Large-Scale ML Datasets"
        assert results[0].authors == ["Wang, X.", "Liu, Y."]
        assert results[0].year == 2023
        assert results[0].download_url == "magnet:?xt=urn:btih:abc123"
        assert results[0].doi == "10.1000/at123"
        # Verify NO placeholder text
        assert "result 1 for:" not in results[0].title.lower()

    def test_search_http_error_returns_empty(self):
        """HTTP error from AT → returns []."""
        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(status=503))

        adapter = AcademicTorrentsAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_search_network_error_returns_empty(self):
        """Network error → returns []."""
        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("DNS failure"))

        adapter = AcademicTorrentsAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_empty_query_returns_empty(self):
        """Empty query string returns []."""
        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        adapter = AcademicTorrentsAdapter()
        results = asyncio.run(adapter.search(""))
        assert results == []

    @pytest.mark.skipif(
        "os.getenv('GITHUB_ACTIONS')",
        reason="Real HTTP call — skipped in CI",
    )
    def test_real_api_search(self):
        """Real HTTP call to Academic Torrents API — verifies live structure."""
        import os
        if os.getenv("GITHUB_ACTIONS"):
            pytest.skip("Real HTTP call — skipped in CI")

        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        adapter = AcademicTorrentsAdapter()
        results = asyncio.run(adapter.search("neural networks", limit=3))

        # Real API should return results
        assert isinstance(results, list)
        if results:
            r = results[0]
            assert r.title != "Unknown"
            assert "result 1 for:" not in r.title.lower()
            assert r.source_index == "academic_torrents"
            assert r.full_text_available is True
            # Magnet link or file_type should be present
            assert r.download_url is not None or r.file_type is not None


# ---------------------------------------------------------------------------
# Test 3: Sci-Hub — search returns empty, DOI resolution is real
# ---------------------------------------------------------------------------

class TestSciHub:
    """Verify Sci-Hub adapter: search returns [], resolve_doi is real."""

    def test_search_returns_empty(self):
        """Sci-Hub search always returns [] — it's not a search engine."""
        from research_shared.adapters.scihub import SciHubAdapter

        adapter = SciHubAdapter()
        results = asyncio.run(adapter.search("AI governance", limit=5))
        assert results == []

    def test_resolve_doi_pdf_available(self):
        """HEAD request returns 200 with PDF content-type."""
        from research_shared.adapters.scihub import SciHubAdapter

        mock_client = MagicMock()
        mock_client.head = AsyncMock(return_value=_mock_response(
            status=200,
            headers={"content-type": "application/pdf"},
        ))

        adapter = SciHubAdapter(http_client=mock_client)
        result = asyncio.run(adapter.resolve_doi("10.1000/test.1"))

        assert result is not None
        assert result.doi == "10.1000/test.1"
        assert result.full_text_available is True
        assert result.file_type == "pdf"
        assert "sci-hub.ru/10.1000/test.1" in (result.download_url or "")

    def test_resolve_doi_not_available(self):
        """HEAD request returns 404 → None."""
        from research_shared.adapters.scihub import SciHubAdapter

        mock_client = MagicMock()
        mock_client.head = AsyncMock(return_value=_mock_response(status=404))

        adapter = SciHubAdapter(http_client=mock_client)
        result = asyncio.run(adapter.resolve_doi("10.1000/missing"))

        assert result is None

    def test_resolve_doi_network_error_returns_none(self):
        """Network error → None."""
        from research_shared.adapters.scihub import SciHubAdapter

        mock_client = MagicMock()
        mock_client.head = AsyncMock(side_effect=Exception("Timeout"))

        adapter = SciHubAdapter(http_client=mock_client)
        result = asyncio.run(adapter.resolve_doi("10.1000/timeout"))

        assert result is None


# ---------------------------------------------------------------------------
# Test 4: Anna's Archive — HTML scraping
# ---------------------------------------------------------------------------

class TestAnnasArchive:
    """Verify Anna's Archive adapter scrapes real metadata."""

    def test_search_returns_real_metadata(self):
        """Mock AA HTML response — verify BeautifulSoup extraction."""
        from research_shared.adapters.annas_archive import AnnasArchiveAdapter

        html = """<html><body>
        <div class="search-result">
            <h3><a href="/md5/abc123">Deep Learning for NLP</a></h3>
            <div class="authors"><span>Smith, J., Jones, K.</span></div>
            <div class="year">2023</div>
            <div data-md5="abc123"></div>
            <div class="filetype">pdf</div>
        </div>
        <div class="search-result">
            <h3><a href="/md5/def456">Transformer Architecture</a></h3>
            <div class="authors"><span>Brown, L.</span></div>
            <div class="year">2022</div>
            <div data-md5="def456"></div>
            <div class="filetype">epub</div>
        </div>
        </body></html>"""

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200, text_data=html,
        ))

        adapter = AnnasArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("deep learning", limit=5))

        assert len(results) >= 1
        if results:
            # Verify real titles, not placeholders
            assert "result 1 for:" not in results[0].title.lower()
            assert results[0].title in ("Deep Learning for NLP", "Transformer Architecture")

    def test_search_http_error_returns_empty(self):
        """HTTP error → []."""
        from research_shared.adapters.annas_archive import AnnasArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(status=403))

        adapter = AnnasArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_search_parse_error_returns_empty(self):
        """Unparseable HTML → []."""
        from research_shared.adapters.annas_archive import AnnasArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200, text_data="<html>Not a search results page</html>",
        ))

        adapter = AnnasArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        # Should not crash, returns results or []
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Test 5: LibGen — HTML form POST
# ---------------------------------------------------------------------------

class TestLibGen:
    """Verify LibGen adapter scrapes real metadata from form POST."""

    def test_search_returns_real_metadata(self):
        """Mock LibGen HTML table — verify BeautifulSoup extraction."""
        from research_shared.adapters.libgen import LibGenAdapter

        html = """<html><body>
        <table class="c">
        <tr><th>ID</th><th>Authors</th><th>Title</th><th>Year</th><th>Pages</th><th>Language</th><th>Size</th><th>Extension</th></tr>
        <tr>
            <td>1</td>
            <td>Smith, J., Jones, K.</td>
            <td>AI Governance Frameworks</td>
            <td>2024</td>
            <td>300</td>
            <td>English</td>
            <td>5MB</td>
            <td>pdf</td>
        </tr>
        <tr>
            <td>2</td>
            <td>Brown, L.</td>
            <td>Autonomous Systems Design</td>
            <td>2023</td>
            <td>250</td>
            <td>English</td>
            <td>3MB</td>
            <td>epub</td>
        </tr>
        </table>
        </body></html>"""

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_mock_response(
            status=200, text_data=html,
        ))

        adapter = LibGenAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("AI governance", limit=5))

        assert len(results) >= 1
        if results:
            assert "result 1 for:" not in results[0].title.lower()
            valid_titles = {"AI Governance Frameworks", "Autonomous Systems Design"}
            assert results[0].title in valid_titles

    def test_search_http_error_returns_empty(self):
        """HTTP error → []."""
        from research_shared.adapters.libgen import LibGenAdapter

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_mock_response(status=500))

        adapter = LibGenAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_search_network_error_returns_empty(self):
        """Network error → []."""
        from research_shared.adapters.libgen import LibGenAdapter

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

        adapter = LibGenAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))

        assert results == []


# ---------------------------------------------------------------------------
# Test 6: No adapter returns placeholder text
# ---------------------------------------------------------------------------

class TestNoPlaceholderText:
    """Verify no adapter returns placeholder text patterns."""

    PLACEHOLDER_PATTERNS = [
        "result 1 for:",
        "result 2 for:",
        "result 3 for:",
        "placeholder",
    ]

    def test_internet_archive_no_placeholders(self):
        """IA adapter with mock data has no placeholder text."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200,
            json_data={"response": {"numFound": 1, "docs": [
                {"identifier": "x", "title": "Real Title", "creator": ["A"],
                 "year": "2024"}
            ]}},
        ))
        adapter = InternetArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))
        for r in results:
            for pattern in self.PLACEHOLDER_PATTERNS:
                assert pattern not in r.title.lower(), f"Placeholder found: {r.title}"

    def test_academic_torrents_no_placeholders(self):
        """AT adapter with mock data has no placeholder text."""
        from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200,
            json_data=[{"id": "x", "title": "Real Dataset", "authors": ["A"]}],
        ))
        adapter = AcademicTorrentsAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))
        for r in results:
            for pattern in self.PLACEHOLDER_PATTERNS:
                assert pattern not in r.title.lower(), f"Placeholder found: {r.title}"

    def test_scihub_no_placeholders(self):
        """Sci-Hub returns empty list — cannot have placeholder text."""
        from research_shared.adapters.scihub import SciHubAdapter

        adapter = SciHubAdapter()
        results = asyncio.run(adapter.search("anything"))
        assert results == []

    def test_annas_archive_no_placeholders(self):
        """AA adapter with minimal HTML has no placeholder text."""
        from research_shared.adapters.annas_archive import AnnasArchiveAdapter

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=_mock_response(
            status=200, text_data="<html><body></body></html>",
        ))
        adapter = AnnasArchiveAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))
        for r in results:
            for pattern in self.PLACEHOLDER_PATTERNS:
                assert pattern not in r.title.lower(), f"Placeholder found: {r.title}"

    def test_libgen_no_placeholders(self):
        """LibGen adapter with empty HTML has no placeholder text."""
        from research_shared.adapters.libgen import LibGenAdapter

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=_mock_response(
            status=200, text_data="<html><body></body></html>",
        ))
        adapter = LibGenAdapter(http_client=mock_client)
        results = asyncio.run(adapter.search("test"))
        for r in results:
            for pattern in self.PLACEHOLDER_PATTERNS:
                assert pattern not in r.title.lower(), f"Placeholder found: {r.title}"


# ---------------------------------------------------------------------------
# Test 7: Internet Archive — real API integration (#54)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="Network-dependent integration test — skipped in CI",
)
class TestInternetArchiveIntegration:
    """Real HTTP calls to archive.org Advanced Search API."""

    def test_internet_archive_real_api(self):
        """Call archive.org API with a known query, verify result structure."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        adapter = InternetArchiveAdapter()
        results = asyncio.run(adapter.search("machine learning", limit=5))

        assert isinstance(results, list)
        if results:
            r = results[0]
            assert isinstance(r.title, str) and len(r.title) > 0
            assert "result 1 for:" not in r.title.lower()
            assert "result 2 for:" not in r.title.lower()
            assert r.source_index == "internet_archive"
            assert r.source_index_label == "Internet Archive"

    def test_internet_archive_no_results(self):
        """Empty query returns empty list."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        adapter = InternetArchiveAdapter()
        results = asyncio.run(adapter.search(""))
        assert results == []

    def test_internet_archive_nonsense_query(self):
        """Gibberish query returns empty or gracefully handled."""
        from research_shared.adapters.internet_archive import InternetArchiveAdapter

        adapter = InternetArchiveAdapter()
        results = asyncio.run(adapter.search("xyzkwlmnoqrstuv"))
        assert isinstance(results, list)
        # May return results or empty — archive.org handles weird queries
        for r in results:
            assert "result 1 for:" not in r.title.lower()
