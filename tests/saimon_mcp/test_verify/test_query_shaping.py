"""Tests for verify shadow-search query shaping (SAIMON-VERIFY-QUERY-SHAPING-1, #199).

The bug: ``_search_sources`` sends the FULL claim sentence to shadow search,
which returns 0 results for long full-sentence queries where a keyword query
returns 5 (live probe: "The Transformer architecture was introduced in 2017" -> 0;
"Transformer architecture attention" -> 5). Abstention stayed at 0.75 because
shadow search found nothing purely due to query form.

The fix: derive a keyword query from the claim (strip stopwords, keep key
terms/entities/numbers, cap length) and fall back to progressively simpler
keyword formulations when the first query returns 0. Fail-closed is preserved.

These tests pin the fix:
1. Keyword extraction drops stopwords and keeps key terms + numbers.
2. ``_search_sources`` sends a keyword query, NOT the full claim.
3. A 0-result first query falls back to a simpler query that returns results.
4. The Transformer regression: keyword query returns sources where the raw
   sentence returned 0.
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
    """httpx.AsyncClient stand-in that records every query it receives."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.queries: list[str] = []
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, json=None, headers=None):
        self.calls += 1
        self.queries.append(json["parameters"]["query"])
        if self._responses:
            return self._responses.pop(0)
        return self._responses[-1] if self._responses else _FakeResponse(200, {})


def _client_returning(results_by_query: dict[str, list[dict]]) -> _FakeAsyncClient:
    """Build a fake whose response depends on the query string."""

    class _QueryAwareClient:
        def __init__(self, mapping) -> None:
            self.mapping = mapping
            self.queries: list[str] = []
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def post(self, url: str, json=None, headers=None):
            self.calls += 1
            query = json["parameters"]["query"]
            self.queries.append(query)
            results = self.mapping.get(query, self.mapping.get("__default__", []))
            return _FakeResponse(200, {"data": {"results": results}})

    return _QueryAwareClient(results_by_query)


class TestKeywordExtraction:
    def test_strips_stopwords_and_keeps_key_terms_and_numbers(self) -> None:
        claim = "The Transformer architecture was introduced in 2017"
        query = verify_server._extract_keyword_query(claim)
        assert query == "Transformer architecture introduced 2017"

    def test_caps_length(self) -> None:
        claim = "a b c d e f g h i j k l m n o p"
        query = verify_server._extract_keyword_query(claim, max_terms=5)
        assert len(query.split()) == 5

    def test_all_stopwords_falls_back_to_raw_tokens(self) -> None:
        claim = "the and of in"
        query = verify_server._extract_keyword_query(claim)
        assert query == "the and of in"

    def test_doi_query_is_passthrough(self) -> None:
        queries = verify_server._search_queries("doi:10.1234/abcd")
        assert queries == ["doi:10.1234/abcd"]


class TestSearchSourcesQueryShaping:
    async def test_sends_keyword_query_not_full_claim(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        claim = "The Transformer architecture was introduced in 2017"
        fake = _client_returning(
            {"__default__": [{"title": "Found Paper"}]}
        )
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources(claim)

        assert results == [{"title": "Found Paper"}]
        assert fake.queries, "no query was sent"
        assert fake.queries[0] != claim
        assert fake.queries[0] == "Transformer architecture introduced 2017"

    async def test_falls_back_when_first_query_returns_zero(self, monkeypatch) -> None:
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        claim = "The Transformer architecture was introduced in 2017 by Google researchers"
        # First (8-term) query returns 0; the 5-term fallback returns results.
        fake = _client_returning({"__default__": [{"title": "Attention Paper"}]})
        # Return empty only for the longest keyword formulation.
        first_query = verify_server._extract_keyword_query(claim, max_terms=8)
        fake.mapping[first_query] = []
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources(claim)

        assert results == [{"title": "Attention Paper"}]
        assert fake.calls >= 2
        assert fake.queries[0] == first_query

    async def test_regression_transformer_claim_gets_sources(self, monkeypatch) -> None:
        """The live-probe regression: full claim -> 0, keyword query -> 5."""
        monkeypatch.setenv("SEARCH_API_KEY", "sk-test")
        claim = "The Transformer architecture was introduced in 2017"
        fake = _client_returning({
            claim: [],  # raw full sentence returns nothing (the old bug)
            "__default__": [
                {"title": f"Source {i}"} for i in range(5)
            ],
        })
        monkeypatch.setattr(verify_server.httpx, "AsyncClient", lambda *a, **k: fake)

        results = await verify_server._search_sources(claim)

        assert len(results) == 5
        assert claim not in fake.queries
