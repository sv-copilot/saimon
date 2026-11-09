"""Universe scoping in the lexical path (#265).

The vector path filters in SQL; the lexical path did not, so a scoped query
returned rows from another universe through the fusion step. Observed live: a
`fiction`-scoped query answered with a reality document.
"""

from __future__ import annotations

import asyncio

from saimon_mcp.search import server as search_server


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *params):
        return self._rows


def _row(id_, universe):
    return {
        "id": id_, "title": "t", "body": "b", "content_type": "claim", "unit_id": None,
        "relevance": 0.5, "doc_status": "ready", "doc_review": "accepted_research",
        "quality_score": None, "primacy_distance_score": None, "universe_id": universe,
        "match_count": 1,
    }


def test_keyword_search_drops_rows_outside_the_universe(monkeypatch):
    pool = _FakePool([_row("a", "u1"), _row("b", "u2")])
    monkeypatch.setattr(search_server, "_db_pool", pool)
    rows = asyncio.run(search_server._keyword_search("rate", 10, None, ["u1"]))
    assert [row["id"] for row in rows] == ["a"]


def test_keyword_search_without_scope_returns_everything(monkeypatch):
    pool = _FakePool([_row("a", "u1"), _row("b", "u2")])
    monkeypatch.setattr(search_server, "_db_pool", pool)
    rows = asyncio.run(search_server._keyword_search("rate", 10, None, None))
    assert len(rows) == 2
