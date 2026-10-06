"""Tests for the offline stub adapter, and for the path it makes provable.

The stub exists so that the whole chain — register a source, search it,
deduplicate, rank — can run with no network and no credentials. These tests
assert both halves: that the adapter behaves like an adapter, and that the chain
genuinely touches nothing outside the process.
"""

import pytest

from research_shared.adapters.base import (
    FulltextFetchResult,
    SourceIndexAdapter,
    SourceSearchResult,
)
from research_shared.adapters.dedup import deduplicate
from research_shared.adapters.ranking import NEUTRAL_POLICY, rank_results
from research_shared.adapters.stub import StubAdapter
from research_shared.source_registry import (
    SourceRegistry,
    adapter_access,
    adapter_kind,
    adapter_label,
)


@pytest.fixture
def adapter() -> StubAdapter:
    return StubAdapter()


class TestProtocolConformance:
    def test_satisfies_the_adapter_protocol(self, adapter):
        """The stub is a real adapter, not a test double."""
        assert isinstance(adapter, SourceIndexAdapter)

    def test_declares_what_it_is(self, adapter):
        assert adapter.name == "stub"
        assert adapter.tier in {"S", "A", "B", "C"}
        assert adapter.trust_model in {"algorithmic", "community", "institutional"}
        assert adapter_label(adapter) == "Stub (offline, synthetic)"
        assert adapter_kind(adapter) == "mixed"
        assert adapter_access(adapter) == "local"

    async def test_result_shape_is_the_canonical_one(self, adapter):
        results = await adapter.search("attention", limit=1)
        assert isinstance(results[0], SourceSearchResult)
        assert results[0].source_index == "stub"
        assert results[0].source_index_label == adapter.label


class TestDeterminism:
    async def test_same_query_gives_the_same_identifiers(self, adapter):
        first = await adapter.search("transformer attention", limit=3)
        second = await adapter.search("transformer attention", limit=3)
        assert [r.identifier for r in first] == [r.identifier for r in second]

    async def test_different_queries_give_different_identifiers(self, adapter):
        a = await adapter.search("attention", limit=1)
        b = await adapter.search("diffusion", limit=1)
        assert a[0].identifier != b[0].identifier

    async def test_fulltext_is_stable(self, adapter):
        result = (await adapter.search("attention", limit=1))[0]
        first = await adapter.fetch_fulltext(result)
        second = await adapter.fetch_fulltext(result)
        assert first.data == second.data

    async def test_empty_query_is_still_answered(self, adapter):
        """A blank query must not raise: callers page through results blindly."""
        assert await adapter.search("", limit=1)


class TestPaging:
    async def test_limit_is_honoured(self, adapter):
        assert len(await adapter.search("q", limit=2)) == 2

    async def test_offset_advances_within_the_stub_set(self, adapter):
        first = await adapter.search("q", limit=1, offset=0)
        second = await adapter.search("q", limit=1, offset=1)
        assert first[0].identifier != second[0].identifier

    async def test_offset_past_the_end_returns_nothing(self, adapter):
        assert await adapter.search("q", limit=10, offset=99) == []

    async def test_zero_limit_returns_nothing(self, adapter):
        assert await adapter.search("q", limit=0) == []


class TestResolutionAndFetch:
    async def test_resolve_doi_returns_a_record(self, adapter):
        result = await adapter.resolve_doi("10.1234/example")
        assert result is not None and result.doi == "10.1234/example"

    async def test_resolve_blank_doi_returns_none(self, adapter):
        assert await adapter.resolve_doi("  ") is None

    async def test_fetch_fulltext_returns_bytes_and_a_type(self, adapter):
        result = (await adapter.search("q", limit=1))[0]
        fetched = await adapter.fetch_fulltext(result)
        assert isinstance(fetched, FulltextFetchResult)
        assert fetched.data and fetched.file_type == "txt"

    async def test_fetched_text_is_labelled_synthetic(self, adapter):
        """Generated text must never be mistakable for a real publication."""
        result = (await adapter.search("q", limit=1))[0]
        fetched = await adapter.fetch_fulltext(result)
        assert b"not a real publication" in fetched.data


class TestTheOfflinePathIsActuallyOffline:
    async def test_the_chain_runs_with_httpx_disabled(self, adapter, monkeypatch):
        """Register, search, dedupe, rank — with any HTTP client poisoned.

        This is the property the public artifact depends on: a stranger can run
        the whole chain on a laptop with no network and no credentials.
        """
        import httpx

        def _no_network(*_args, **_kwargs):
            raise AssertionError("the stub path attempted a network call")

        monkeypatch.setattr(httpx, "Client", _no_network)
        monkeypatch.setattr(httpx, "AsyncClient", _no_network)

        registry = SourceRegistry()
        registry.register(adapter)
        assert registry.list_names() == ["stub"]

        collected: list[SourceSearchResult] = []
        for selected in registry.select(["stub"]):
            collected.extend(await selected.search("verifiable research", limit=3))

        deduped = deduplicate(collected)
        ranked = rank_results(deduped, policy=NEUTRAL_POLICY)

        assert ranked, "the offline chain produced nothing"
        assert all(r.source_index == "stub" for r in ranked)

    async def test_the_stub_is_registrable_and_selectable(self, adapter):
        registry = SourceRegistry()
        registry.register_all([adapter])
        assert registry.get("stub") is adapter
        assert [a.name for a in registry.select(["stub"])] == ["stub"]
        assert registry.labels() == {"stub": "Stub (offline, synthetic)"}
