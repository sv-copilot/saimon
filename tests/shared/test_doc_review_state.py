"""Document review state (SAIMON-DOC-REVIEW-STATE-1).

Every document had equal standing, so a government form's boilerplate competed
with a peer-reviewed survey on the same vector distance. Review status lets the
operator say what counts as evidence, and retrieval honours it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from research_shared.review import (
    ACCEPTED_RESEARCH,
    DEFAULT_REVIEW_STATUS,
    REJECTED,
    filter_by_review,
    normalise_review_statuses,
    review_counts,
    set_review_status,
)


class TestNormalisation:
    def test_default_is_accepted_research(self):
        assert normalise_review_statuses(None) == [ACCEPTED_RESEARCH]
        assert DEFAULT_REVIEW_STATUS == ACCEPTED_RESEARCH

    def test_accepts_a_single_string(self):
        assert normalise_review_statuses("rejected") == [REJECTED]

    def test_rejects_unknown_values(self):
        with pytest.raises(ValueError):
            normalise_review_statuses(["banana"])

    def test_empty_list_falls_back_to_default(self):
        assert normalise_review_statuses([]) == [ACCEPTED_RESEARCH]


class TestFiltering:
    def test_default_hides_non_accepted_documents(self):
        rows = [
            {"id": "1", "doc_review": "accepted_research"},
            {"id": "2", "doc_review": "rejected"},
            {"id": "3"},  # missing status = default
        ]
        assert [r["id"] for r in filter_by_review(rows)] == ["1", "3"]

    def test_explicit_filter_widens(self):
        rows = [{"id": "1", "doc_review": "rejected"}, {"id": "2", "doc_review": "general_context"}]
        assert [r["id"] for r in filter_by_review(rows, ["rejected", "general_context"])] == ["1", "2"]

    def test_unknown_status_on_a_row_is_not_returned_by_default(self):
        rows = [{"id": "1", "doc_review": "needs_user_clarification"}]
        assert filter_by_review(rows) == []


class _FakeDB:
    def __init__(self, rows=None):
        self.statements = []
        self._rows = rows or []

    async def execute(self, query, *args):
        self.statements.append((query, args))
        return "OK"

    async def fetch(self, query, *args):
        return self._rows


class TestWrites:
    def test_status_is_written_to_metadata(self):
        db = _FakeDB()
        asyncio.run(set_review_status(db, doi="url:x", status=REJECTED))
        patch = json.loads(next(a for q, a in db.statements if "UPDATE" in q)[0])
        assert patch == {"review_status": REJECTED}

    def test_unknown_status_is_rejected(self):
        with pytest.raises(ValueError):
            asyncio.run(set_review_status(_FakeDB(), doi="url:x", status="banana"))

    def test_counts_group_by_status(self):
        db = _FakeDB(rows=[{"status": "accepted_research", "n": 40},
                           {"status": "rejected", "n": 5}])
        assert asyncio.run(review_counts(db)) == {"accepted_research": 40, "rejected": 5}


class TestRetrievalWiring:
    def test_search_selects_and_filters_review_status(self):
        import inspect

        from saimon_mcp.search import server

        assert "COALESCE(metadata->>'review_status', 'accepted_research') as doc_review" in (
            inspect.getsource(server._vector_search)
        )
        assert "filter_by_review" in inspect.getsource(server._retrieve_and_rerank)

    def test_explore_filters_review_status(self):
        import inspect

        from saimon_mcp.explore import server as explore

        assert "doc_review" in inspect.getsource(explore)
        assert "filter_by_review" in inspect.getsource(explore)
