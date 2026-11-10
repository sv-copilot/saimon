"""The requery path must keep the scope (#265).

A weak first pass reformulates the query and searches again. That second path
forgot the universe and the fact filter, so a scoped query could be answered
with out-of-scope content — observed live: a `needle` query returned a research
paper, and a reality query returned a Needle character.
"""

from __future__ import annotations

import asyncio

from research_shared.rerank import RerankConfig
from saimon_mcp.search import server as search_server


def _candidates(prefix: str):
    return [
        {
            "id": f"{prefix}-{i}", "title": f"{prefix} {i}", "body": "body", "content_type": "claim",
            "unit_id": None, "relevance_score": 0.9, "quality_score": None,
            "primacy_distance_score": None, "universe_id": "u",
        }
        for i in range(3)
    ]


def test_requery_is_scoped(monkeypatch):
    seen: list[tuple] = []

    async def fake_search(query, limit, user_id, fact_filter=None, universe_ids=None):
        seen.append((query, tuple(universe_ids or ())))
        return _candidates("a")

    def fake_rerank(query, candidates, cfg=None, **_kwargs):
        from research_shared.rerank import RerankOutcome

        return RerankOutcome(
            ranked=[], top_score=0.30, second_score=0.20, margin_gap=0.10,
            candidate_count=len(candidates), kept_count=0, fail_safe_fired=True,
            lexical_support=True, abstain_reason="floor",
        )

    monkeypatch.setattr(search_server, "_search_candidates", fake_search)
    monkeypatch.setattr(search_server, "rerank", fake_rerank)
    monkeypatch.setattr(
        search_server, "get_rerank_config", lambda: RerankConfig(max_requery=1), raising=False
    )

    class _Log:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    asyncio.run(
        search_server._retrieve_and_rerank(
            "who is sergeant kade", 3, None, _Log(), False, None, None, ["u-needle"]
        )
    )
    assert len(seen) >= 2, "requery did not run"
    assert all(scope == ("u-needle",) for _q, scope in seen), seen
