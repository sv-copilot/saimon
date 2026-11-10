"""Regression tests for SAIMON-KG-SEARCH-FIX-1 — vector/keyword parity.

The historical bug: search_knowledge_graph returned 0 rows because the keyword
fallback only ran when the vector path returned empty. A no-embedding node was
silently dropped whenever the vector path returned some (non-empty) results.
These tests pin the merged behaviour so no-embedding nodes are always reachable
lexically, with parity to explore_content.
"""


class TestMergeResults:
    def test_fusion_ranks_agreement_first(self):
        """A doc both paths agree on outranks one that only the vector path saw.

        This replaces the old "vector leads" contract: rank fusion is the point
        of #256, so a hit at rank 2 in both lists beats a rank-1/absent split.
        """
        from saimon_mcp.search import server

        merged = server._merge_results(
            [{"id": "a"}, {"id": "b"}],
            [{"id": "b"}, {"id": "c"}],
            10,
        )
        assert [r["id"] for r in merged] == ["b", "a", "c"]

    def test_limit_caps_after_fusion(self):
        """A lexical rank-1 hit is no longer discarded when vectors fill the quota."""
        from saimon_mcp.search import server

        merged = server._merge_results(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            [{"id": "d"}],
            2,
        )
        assert [r["id"] for r in merged] == ["a", "d"]

    def test_keyword_fills_no_embedding_gap(self):
        """A no-embedding node (only reachable lexically) is included even when
        the vector path returns non-empty results."""
        from saimon_mcp.search import server

        merged = server._merge_results(
            [{"id": "embedded-1"}],
            [{"id": "no-embedding-1"}],
            10,
        )
        assert [r["id"] for r in merged] == ["embedded-1", "no-embedding-1"]

    def test_empty_both_returns_empty(self):
        from saimon_mcp.search import server

        assert server._merge_results([], [], 10) == []


class TestKeywordSearch:
    async def test_returns_lexical_matches(self, monkeypatch):
        from saimon_mcp.search import server

        rows = [{"id": "kw-1", "title": "Sprocket bartender", "relevance": 0.5,
                 "universe_id": "reality"}]

        class _Pool:
            async def fetch(self, query, *args):
                return rows

        monkeypatch.setattr(server, "_db_pool", _Pool())

        result = await server._keyword_search("sprocket", 10, None, ["reality"])
        assert [r["id"] for r in result] == ["kw-1"]
        assert result[0]["id"] == "kw-1"

    async def test_no_pool_returns_empty(self, monkeypatch):
        from saimon_mcp.search import server

        monkeypatch.setattr(server, "_db_pool", None)
        assert await server._keyword_search("x", 10, None, ["reality"]) == []
