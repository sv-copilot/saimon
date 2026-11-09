"""Tests for SAIMON-RETRIEVAL-RERANK-1 — passage-level rerank + fail-safe gate.

Covers the four acceptance criteria:

- a query returns top-K passages ranked by relevance score, not adapter order
- a query whose candidates are all below ``min_relevance`` returns
  ``no_strong_evidence: true`` (fail-safe) instead of a weak answer
- the fail-safe re-queries once with a reformulated query before giving up
- the ``retrieval.rerank`` audit event records candidate/kept/top-score/fail-safe
"""

from __future__ import annotations

import io
import json

from research_shared.rerank import RerankConfig, reformulate_query, rerank


def _candidate(identifier, title, body="", similarity=None):
    """Build a knowledge-graph candidate dict in the shape search produces."""
    candidate = {
        "id": identifier,
        "title": title,
        "body": body,
        "content_type": "note",
        "relevance": 0.5,
    }
    if similarity is not None:
        candidate["similarity"] = similarity
    return candidate


# ---------------------------------------------------------------------------
# rank order (relevance-scored, not adapter order)
# ---------------------------------------------------------------------------


class TestRerankRankOrder:
    def test_ranks_by_relevance_not_input_order(self):
        """Passages are ordered by relevance score, not the order passed in."""
        candidates = [
            _candidate("weak-a", "unrelated", "banana"),
            _candidate("strong", "query", "the query is here"),
            _candidate("weak-b", "also unrelated", "apple"),
        ]
        outcome = rerank(
            "query",
            candidates,
            RerankConfig(min_relevance=0.0, top_k=3),
        )
        assert [r["id"] for r in outcome.ranked] == ["strong", "weak-a", "weak-b"]
        assert outcome.fail_safe_fired is False

    def test_per_passage_relevance_score_present(self):
        """Each ranked passage carries a per-passage relevance score in [0, 1]."""
        outcome = rerank(
            "query",
            [_candidate("a", "query", "query query query")],
            RerankConfig(min_relevance=0.0),
        )
        assert "relevance_score" in outcome.ranked[0]
        assert 0.0 <= outcome.ranked[0]["relevance_score"] <= 1.0

    def test_top_k_truncates(self):
        """Only the top-K passages are returned.

        Both gates are disabled here on purpose: this test pins TRUNCATION, and
        the margin gate (#234) would abstain on evenly-spaced scores.  The
        gates themselves are covered in test_abstain.py.
        """
        candidates = [
            _candidate(f"c{i}", f"query {i}", f"query {i} query", similarity=0.9 - i * 0.1)
            for i in range(5)
        ]
        outcome = rerank(
            "query", candidates, RerankConfig(min_relevance=0.0, min_margin=0.0, top_k=3)
        )
        assert len(outcome.ranked) == 3
        assert outcome.kept_count == 3
        assert outcome.candidate_count == 5


# ---------------------------------------------------------------------------
# fail-safe no-answer gate
# ---------------------------------------------------------------------------


class TestFailSafeGate:
    def test_all_below_threshold_fires_fail_safe(self):
        """When nothing clears min_relevance the outcome is empty + flagged."""
        outcome = rerank(
            "query",
            [
                _candidate("low-a", "unrelated", "banana"),
                _candidate("low-b", "also unrelated", "apple"),
            ],
            RerankConfig(min_relevance=0.9, top_k=3),
        )
        assert outcome.fail_safe_fired is True
        assert outcome.ranked == []
        assert outcome.kept_count == 0

    def test_empty_candidates_fire_fail_safe(self):
        """No candidates means no strong evidence, not a weak answer."""
        outcome = rerank("query", [], RerankConfig(min_relevance=0.25))
        assert outcome.fail_safe_fired is True
        assert outcome.ranked == []
        assert outcome.top_score == 0.0


# ---------------------------------------------------------------------------
# reformulated re-query
# ---------------------------------------------------------------------------


class TestReformulateQuery:
    def test_reformulation_differs_from_original(self):
        assert reformulate_query("original query") != "original query"

    def test_reformulation_is_deterministic(self):
        assert reformulate_query("the quick brown fox") == reformulate_query(
            "the quick brown fox"
        )


# ---------------------------------------------------------------------------
# endpoint wiring: re-query once + audit field
# ---------------------------------------------------------------------------


class TestSearchEndpointReranks:
    def test_results_ranked_by_relevance_score(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """The endpoint returns results sorted by relevance score, not adapter order."""
        from saimon_mcp.search import server

        async def fake_search(query, limit, user_id, fact_filter=None):
            # Adapter order: weak lexical hit first, strong semantic hit second.
            return [
                _candidate("weak", "banana", "apple"),
                _candidate("strong", "query", "query query query", similarity=0.95),
            ]

        monkeypatch.setattr(server, "_search_candidates", fake_search)
        monkeypatch.setattr(
            server,
            "_rerank_config",
            RerankConfig(min_relevance=0.0, top_k=10, max_requery=1),
        )
        monkeypatch.setattr(server, "_rerank_embed_fn", lambda: (lambda text: None))
        monkeypatch.setattr(server, "_db_pool", object())

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "query", "limit": 2},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        results = data["data"]["results"]
        assert [r["id"] for r in results] == ["strong", "weak"]
        assert results[0]["relevance_score"] > results[1]["relevance_score"]
        assert data["data"]["no_strong_evidence"] is False


class TestSearchEndpointFailSafe:
    def test_below_threshold_returns_no_strong_evidence(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """All-below-threshold candidates produce no_strong_evidence, not weak hits."""
        from saimon_mcp.search import server

        async def fake_search(query, limit, user_id, fact_filter=None):
            return [_candidate("low", "unrelated", "banana", similarity=0.0)]

        monkeypatch.setattr(server, "_search_candidates", fake_search)
        monkeypatch.setattr(
            server,
            "_rerank_config",
            RerankConfig(min_relevance=0.9, top_k=10, max_requery=1),
        )
        monkeypatch.setattr(server, "_rerank_embed_fn", lambda: (lambda text: None))
        monkeypatch.setattr(server, "_db_pool", object())

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "query", "limit": 10},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["no_strong_evidence"] is True
        assert data["data"]["results"] == []
        assert data["data"]["total"] == 0

    def test_requeries_once_with_reformulated_query(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """Fail-safe re-queries exactly once with a reformulated query."""
        from saimon_mcp.search import server

        calls: list[str] = []

        async def fake_search(query, limit, user_id, fact_filter=None):
            calls.append(query)
            if query == "original query":
                return [_candidate("low", "unrelated", "banana", similarity=0.0)]
            # The reformulated query finds a strong passage.
            return [_candidate("strong", "original query", "original query", similarity=0.95)]

        monkeypatch.setattr(server, "_search_candidates", fake_search)
        monkeypatch.setattr(
            server,
            "_rerank_config",
            RerankConfig(min_relevance=0.9, top_k=10, max_requery=1),
        )
        monkeypatch.setattr(server, "_rerank_embed_fn", lambda: (lambda text: None))
        monkeypatch.setattr(server, "_db_pool", object())

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "original query", "limit": 10},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert len(calls) == 2
        assert calls[1] != calls[0]
        assert data["data"]["no_strong_evidence"] is False
        assert data["data"]["results"][0]["id"] == "strong"


class TestRetrievalRerankAudit:
    def test_audit_field_records_rerank_metrics(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """The retrieval.rerank audit event records candidate/kept/top-score/fail-safe."""
        from research_shared.audit import AuditLogger
        from saimon_mcp.search import server

        buffer = io.StringIO()

        def fake_build_logger(payload, request, auth, service_name):
            return AuditLogger(
                trace_id=payload.trace_id,
                service_name=service_name,
                output=buffer,
            )

        async def fake_search(query, limit, user_id, fact_filter=None):
            return [
                _candidate("strong", "query", "query query query", similarity=0.95),
                _candidate("weak", "unrelated", "banana", similarity=0.1),
            ]

        monkeypatch.setattr(server, "build_audit_logger", fake_build_logger)
        monkeypatch.setattr(server, "_search_candidates", fake_search)
        monkeypatch.setattr(
            server,
            "_rerank_config",
            RerankConfig(min_relevance=0.2, top_k=10, max_requery=1),
        )
        monkeypatch.setattr(server, "_rerank_embed_fn", lambda: (lambda text: None))
        monkeypatch.setattr(server, "_db_pool", object())

        client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "query", "limit": 10},
            },
            headers=auth_headers,
        )

        events = [
            json.loads(line)
            for line in buffer.getvalue().splitlines()
            if line.strip()
        ]
        rerank_events = [e for e in events if e.get("event") == "retrieval.rerank"]
        assert rerank_events, "expected a retrieval.rerank audit event"

        event = rerank_events[0]
        assert event["candidate_count"] == 2
        assert event["kept_count"] == 2
        assert event["top_score"] > 0
        assert event["fail_safe_fired"] is False
        assert "requery_count" in event
