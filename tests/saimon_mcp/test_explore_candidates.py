"""explore_content candidate retrieval (SAIMON-EXPLORE-CANDIDATES-1).

Observed live: `explore_content` returned 0 results for "pgvector" and for
"entity resolution blocking" while `search_knowledge_graph` answered both. The
candidate query used one `%query%` pattern, which only matches the query as a
contiguous phrase, so a natural-language question never produced candidates and
the reranker had nothing to rank.
"""

from __future__ import annotations

from saimon_mcp.explore.server import candidate_patterns


class TestCandidatePatterns:
    def test_multi_word_query_becomes_per_word_patterns(self):
        patterns = candidate_patterns("entity resolution blocking")
        assert "%entity%" in patterns
        assert "%resolution%" in patterns
        assert "%blocking%" in patterns
        assert not any("entity resolution blocking" in p for p in patterns)

    def test_single_word_still_works(self):
        assert candidate_patterns("pgvector") == ["%pgvector%"]

    def test_stopwords_do_not_become_patterns(self):
        patterns = candidate_patterns("who won the 2024 super bowl")
        assert "%the%" not in patterns
        assert "%2024%" not in patterns

    def test_empty_query_has_no_patterns(self):
        assert candidate_patterns("   ") == []

    def test_pattern_count_is_bounded(self):
        long_query = "alpha beta gamma delta epsilon zeta eta theta"
        assert len(candidate_patterns(long_query)) <= 6
