"""Tests for the Unpaywall adapter.

Two behaviours here are the whole point of the adapter, and both are easy to get
wrong:

1. It never calls the **retired search endpoint**. ``/v2/search`` answers
   ``410 Gone`` since 18 September 2026, so ``search`` must be an offline no-op.
2. It never calls the API **without the caller's own email**. The vendor refuses
   placeholder identities, so an unconfigured adapter declines instead of
   inventing one.
"""

import httpx
import pytest
import respx

from research_shared.adapters.base import SourceIndexAdapter
from research_shared.adapters.unpaywall import (
    CONTACT_EMAIL_ENV,
    UNPAYWALL_DOI_URL,
    UnpaywallAdapter,
)

DOI = "10.1038/nature12373"

#: A trimmed but structurally exact DOI object.
DOI_OBJECT = {
    "doi": DOI,
    "title": "Structure of the human glucagon receptor",
    "year": 2013,
    "is_oa": True,
    "best_oa_location": {
        "url_for_pdf": "https://example.org/oa/paper.pdf",
        "url": "https://example.org/oa/landing",
        "host_type": "repository",
        "version": "publishedVersion",
    },
    "oa_locations": [
        {"url_for_pdf": None, "url": "https://example.org/other"},
        {"url_for_pdf": "https://example.org/oa/paper.pdf"},
    ],
    "z_authors": [{"raw_author_name": "Si J. Si"}],
}


@pytest.fixture
def adapter() -> UnpaywallAdapter:
    return UnpaywallAdapter(email="research@example.org")


class TestProtocolConformance:
    def test_is_a_source_adapter(self, adapter):
        assert isinstance(adapter, SourceIndexAdapter)

    def test_declares_that_it_needs_an_identity(self, adapter):
        assert adapter.name == "unpaywall"
        assert adapter.label == "Unpaywall"
        assert adapter.access == "credentialed"

    def test_declares_itself_available_only_with_a_contact_address(self):
        assert UnpaywallAdapter(email="a@b.org").available is True
        assert UnpaywallAdapter(email=None, timeout=1).available is False


class TestItNeverCallsTheRetiredSearchEndpoint:
    @respx.mock
    async def test_search_is_an_offline_no_op(self, adapter):
        any_request = respx.route(host="api.unpaywall.org").mock(
            return_value=httpx.Response(410, json={"error": "Gone"})
        )
        assert await adapter.search("anything", limit=10) == []
        assert not any_request.called, "the retired search endpoint was called"

    @respx.mock
    async def test_search_stays_a_no_op_without_an_email(self):
        adapter = UnpaywallAdapter(email=None, timeout=1)
        route = respx.route(host="api.unpaywall.org").mock(
            return_value=httpx.Response(200, json={})
        )
        assert await adapter.search("anything", limit=10) == []
        assert not route.called


class TestItNeverCallsWithoutAnIdentity:
    @respx.mock
    async def test_resolve_declines_without_an_email(self):
        adapter = UnpaywallAdapter(email=None, timeout=1)
        route = respx.get(url__startswith=f"{UNPAYWALL_DOI_URL}/").mock(
            return_value=httpx.Response(200, json=DOI_OBJECT)
        )
        assert await adapter.resolve_doi(DOI) is None
        assert not route.called, "the API was called without the caller's own email"

    def test_env_var_supplies_the_identity(self, monkeypatch):
        monkeypatch.setenv(CONTACT_EMAIL_ENV, "someone@their-own.org")
        assert UnpaywallAdapter().email == "someone@their-own.org"

    def test_blank_env_var_is_not_an_identity(self, monkeypatch):
        monkeypatch.setenv(CONTACT_EMAIL_ENV, "   ")
        assert UnpaywallAdapter().available is False


class TestResolution:
    @respx.mock
    async def test_maps_an_open_work(self, adapter):
        route = respx.get(f"{UNPAYWALL_DOI_URL}/{DOI}").mock(
            return_value=httpx.Response(200, json=DOI_OBJECT)
        )
        result = await adapter.resolve_doi(f"https://doi.org/{DOI}")

        assert result is not None
        assert result.doi == DOI
        assert result.title.startswith("Structure of the human")
        assert result.year == 2013
        assert result.authors == ["Si J. Si"]
        assert result.full_text_available is True
        assert result.download_url == "https://example.org/oa/paper.pdf"
        assert route.calls[0].request.url.params["email"] == "research@example.org"

    @respx.mock
    async def test_a_closed_work_has_no_copy_to_fetch(self, adapter):
        closed = {**DOI_OBJECT, "is_oa": False, "best_oa_location": None, "oa_locations": []}
        respx.get(f"{UNPAYWALL_DOI_URL}/{DOI}").mock(
            return_value=httpx.Response(200, json=closed)
        )
        result = await adapter.resolve_doi(DOI)
        assert result is not None
        assert result.full_text_available is False
        assert result.download_url is None
        assert await adapter.fetch_fulltext(result) is None

    @respx.mock
    async def test_unknown_doi_returns_none(self, adapter):
        respx.get(url__startswith=f"{UNPAYWALL_DOI_URL}/").mock(
            return_value=httpx.Response(404)
        )
        assert await adapter.resolve_doi("10.9999/nope") is None

    @respx.mock
    async def test_a_rejected_identity_is_not_retried(self, adapter):
        """422 means the vendor refused the caller: retrying cannot help."""
        route = respx.get(url__startswith=f"{UNPAYWALL_DOI_URL}/").mock(
            return_value=httpx.Response(422, json={"message": "use your own email"})
        )
        assert await adapter.resolve_doi(DOI) is None
        assert route.call_count == 1

    async def test_blank_doi_makes_no_request(self, adapter):
        assert await adapter.resolve_doi("   ") is None

    @respx.mock
    async def test_transport_error_is_retried_once(self, adapter):
        route = respx.get(url__startswith=f"{UNPAYWALL_DOI_URL}/").mock(
            side_effect=httpx.ConnectError("no route")
        )
        assert await adapter.resolve_doi(DOI) is None
        assert route.call_count == 2
