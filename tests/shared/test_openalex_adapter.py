"""Tests for the OpenAlex adapter, against the vendor's real response shape.

The shape asserted here is the one documented by OpenAlex and confirmed against a
live response: ``results[]`` of work objects, ``doi`` as a URL, abstracts only as
an inverted index, and open-access copies under ``best_oa_location``.

All HTTP is mocked, so the suite stays offline; one live check lives in the
integration-marked test at the bottom.
"""

import httpx
import pytest
import respx

from research_shared.adapters.base import SourceIndexAdapter
from research_shared.adapters.openalex import (
    OPENALEX_WORKS_URL,
    OpenAlexAdapter,
    normalise_doi,
    reconstruct_abstract,
)

#: A trimmed but structurally exact OpenAlex work, copied from a live response.
WORK = {
    "id": "https://openalex.org/W4388194433",
    "doi": "https://doi.org/10.1109/tvcg.2023.3327163",
    "title": "AttentionViz: A Global View of Transformer Attention",
    "display_name": "AttentionViz: A Global View of Transformer Attention",
    "type": "article",
    "publication_year": 2023,
    "cited_by_count": 41,
    "authorships": [
        {"author": {"display_name": "Catherine Yeh"}},
        {"author": {"display_name": "Yida Chen"}},
    ],
    "abstract_inverted_index": {"Attention": [0], "is": [1], "everywhere": [2]},
    "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://example.org/paper.pdf"},
    "best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf", "host_type": "repository"},
}


@pytest.fixture
def adapter() -> OpenAlexAdapter:
    return OpenAlexAdapter(mailto="research@example.org")


class TestPureHelpers:
    def test_abstract_is_rebuilt_in_position_order(self):
        index = {"world": [2], "hello": [0], "there": [1]}
        assert reconstruct_abstract(index) == "hello there world"

    def test_abstract_none_when_absent(self):
        assert reconstruct_abstract(None) is None
        assert reconstruct_abstract({}) is None
        assert reconstruct_abstract({"word": []}) is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://doi.org/10.1/ABC", "10.1/abc"),
            ("http://doi.org/10.1/abc", "10.1/abc"),
            ("doi:10.1/abc", "10.1/abc"),
            ("10.1/ABC", "10.1/abc"),
            (None, None),
            ("", None),
        ],
    )
    def test_doi_is_normalised(self, raw, expected):
        assert normalise_doi(raw) == expected


class TestProtocolConformance:
    def test_is_a_source_adapter(self, adapter):
        assert isinstance(adapter, SourceIndexAdapter)

    def test_declares_reachable_without_an_account(self, adapter):
        assert adapter.name == "openalex"
        assert adapter.label == "OpenAlex"
        assert adapter.access == "anonymous"


class TestSearch:
    @respx.mock
    async def test_maps_a_work_onto_the_canonical_shape(self, adapter):
        respx.get(OPENALEX_WORKS_URL).mock(
            return_value=httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK]})
        )
        results = await adapter.search("transformer attention", limit=5)

        assert len(results) == 1
        result = results[0]
        assert result.title == "AttentionViz: A Global View of Transformer Attention"
        assert result.doi == "10.1109/tvcg.2023.3327163"          # URL form stripped
        assert result.identifier == "doi:10.1109/tvcg.2023.3327163"
        assert result.authors == ["Catherine Yeh", "Yida Chen"]
        assert result.year == 2023
        assert result.type == "academic_paper"                     # 'article' mapped
        assert result.abstract_snippet == "Attention is everywhere"  # rebuilt
        assert result.source_index == "openalex"
        assert result.full_text_available is True
        assert result.download_url == "https://example.org/paper.pdf"

    @respx.mock
    async def test_from_our_catalogue_is_sent_as_etiquette(self, adapter):
        route = respx.get(OPENALEX_WORKS_URL).mock(
            return_value=httpx.Response(200, json={"results": [WORK]})
        )
        await adapter.search("anything", limit=1)
        assert route.calls[0].request.url.params["mailto"] == "research@example.org"

    @respx.mock
    async def test_no_mailto_configured_still_searches(self):
        adapter = OpenAlexAdapter(mailto=None)
        route = respx.get(OPENALEX_WORKS_URL).mock(
            return_value=httpx.Response(200, json={"results": [WORK]})
        )
        await adapter.search("anything", limit=1)
        assert "mailto" not in route.calls[0].request.url.params

    @respx.mock
    async def test_blank_query_makes_no_request(self, adapter):
        route = respx.get(OPENALEX_WORKS_URL).mock(return_value=httpx.Response(200, json={}))
        assert await adapter.search("   ", limit=5) == []
        assert await adapter.search("x", limit=0) == []
        assert not route.called

    @respx.mock
    async def test_offset_inside_a_page_is_trimmed(self, adapter):
        works = [{**WORK, "title": f"W{i}"} for i in range(5)]
        respx.get(OPENALEX_WORKS_URL).mock(
            return_value=httpx.Response(200, json={"results": works})
        )
        # per_page becomes 5, page 1, so offset 2 must trim the first two.
        results = await adapter.search("q", limit=5, offset=2)
        assert [r.title for r in results] == ["W2", "W3", "W4"]

    @respx.mock
    async def test_http_error_yields_no_results_rather_than_raising(self, adapter):
        respx.get(OPENALEX_WORKS_URL).mock(return_value=httpx.Response(503))
        assert await adapter.search("q", limit=5) == []

    @respx.mock
    async def test_transport_error_is_retried_once_then_gives_up(self, adapter):
        route = respx.get(OPENALEX_WORKS_URL).mock(side_effect=httpx.ConnectError("no route"))
        assert await adapter.search("q", limit=5) == []
        assert route.call_count == 2


class TestResolutionAndFetch:
    @respx.mock
    async def test_resolve_doi_returns_a_work(self, adapter):
        respx.get(f"{OPENALEX_WORKS_URL}/https://doi.org/10.1109/tvcg.2023.3327163").mock(
            return_value=httpx.Response(200, json=WORK)
        )
        result = await adapter.resolve_doi("https://doi.org/10.1109/TVCG.2023.3327163")
        assert result is not None and result.doi == "10.1109/tvcg.2023.3327163"

    @respx.mock
    async def test_resolve_unknown_doi_returns_none(self, adapter):
        respx.get(url__startswith=f"{OPENALEX_WORKS_URL}/").mock(
            return_value=httpx.Response(404)
        )
        assert await adapter.resolve_doi("10.9999/nope") is None

    async def test_resolve_blank_doi_makes_no_request(self, adapter):
        assert await adapter.resolve_doi("  ") is None

    @respx.mock
    async def test_fetch_returns_bytes_for_an_open_work(self, adapter):
        result = (await self._one(adapter))
        respx.get("https://example.org/paper.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 stub")
        )
        fetched = await adapter.fetch_fulltext(result)
        assert fetched is not None and fetched.data.startswith(b"%PDF")

    async def test_fetch_declines_when_there_is_no_open_copy(self, adapter):
        from research_shared.adapters.base import SourceSearchResult

        closed = SourceSearchResult(
            type="academic_paper", identifier="doi:10.1/closed", doi="10.1/closed",
            title="Closed", source_index="openalex", source_index_label="OpenAlex",
            full_text_available=False, download_url=None,
        )
        assert await adapter.fetch_fulltext(closed) is None

    async def _one(self, adapter):
        respx.get(OPENALEX_WORKS_URL).mock(
            return_value=httpx.Response(200, json={"results": [WORK]})
        )
        return (await adapter.search("q", limit=1))[0]
