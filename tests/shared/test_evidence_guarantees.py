"""The three guarantees the evidence path now makes (#347).

Determinism, scope and stance each had a defect that made a verdict depend on
something other than the corpus: row arrival order, a missing universe filter,
and a constant polarity. These tests pin the fix at the level the defect lived.
"""

from __future__ import annotations

import random

import pytest

from research_shared.evidence import (
    EVIDENCE_SQL,
    EVIDENCE_SQL_SCOPED,
    classify_stance,
    collect_corpus_evidence,
)
from research_shared.verification import counts

CLAIM = "pgvector supports HNSW indexes"

BODY = (
    "pgvector supports HNSW and IVFFlat indexes. An HNSW index trades build time "
    "for query speed, and the operator can tune ef_search at query time. "
)


def _row(node_id: str, body: str = BODY, title: str = "pgvector README") -> dict:
    return {
        "id": node_id,
        "title": title,
        "body": body,
        "content_type": "fulltext_chunk",
        "doi": "",
    }


class FakeDB:
    """Records the SQL it was given and returns a fixed row set."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql: str, *args):
        self.calls.append((sql, args))
        return list(self.rows)


def test_evidence_sql_orders_before_limiting() -> None:
    # Without ORDER BY the planner is free to return a different 200 rows per
    # execution, which is how one claim produced two answers across 18 calls.
    assert "ORDER BY id" in EVIDENCE_SQL
    assert EVIDENCE_SQL.index("ORDER BY") < EVIDENCE_SQL.index("LIMIT")


@pytest.mark.asyncio
async def test_ranking_does_not_depend_on_row_order() -> None:
    rows = [_row(f"00000000-0000-4000-8000-0000000000{i:02d}") for i in range(10)]

    async def run(ordering: list[dict]):
        return await collect_corpus_evidence(FakeDB(ordering), CLAIM)

    first = await run(rows)
    shuffled = rows[:]
    random.Random(1234).shuffle(shuffled)
    second = await run(shuffled)

    assert [item["evidence_source"] for item in first] == [
        item["evidence_source"] for item in second
    ]


@pytest.mark.asyncio
async def test_scoped_query_filters_by_universe() -> None:
    db = FakeDB([_row("00000000-0000-4000-8000-000000000001")])
    await collect_corpus_evidence(
        db, CLAIM, universe_ids={"00000000-0000-4000-8000-000000000001"}
    )
    sql, args = db.calls[0]
    assert sql == EVIDENCE_SQL_SCOPED
    assert "universe_id = ANY($3::uuid[])" in sql
    assert args[2] == ["00000000-0000-4000-8000-000000000001"]


@pytest.mark.asyncio
async def test_unscoped_query_has_no_universe_predicate() -> None:
    db = FakeDB([])
    await collect_corpus_evidence(db, CLAIM, universe_ids=None)
    sql, _ = db.calls[0]
    assert sql == EVIDENCE_SQL
    assert "universe_id" not in sql


@pytest.mark.asyncio
async def test_empty_scope_is_a_refusal_not_a_widening() -> None:
    # An unreadable universe must return nothing. Falling back to the whole
    # corpus is the failure this pins.
    db = FakeDB([_row("00000000-0000-4000-8000-000000000001")])
    result = await collect_corpus_evidence(db, CLAIM, universe_ids=set())
    assert result == []
    assert db.calls == []


@pytest.mark.parametrize(
    "passage,expected",
    [
        (BODY, "supports"),
        (
            (
                "It is not true that pgvector supports HNSW indexes; the extension "
                "documents IVFFlat only, and HNSW support is absent from the release."
            ),
            "contradicts",
        ),
        (
            (
                "pgvector supports cosine distance and inner product operators. "
                "The manual lists both for the vector type."
            ),
            "supports",
        ),
    ],
)
def test_stance_classification(passage: str, expected: str) -> None:
    assert classify_stance(CLAIM, passage) == expected


def test_real_pgvector_page_is_not_a_contradiction() -> None:
    # This passage was labelled "contradicts" by the 60-char either-side window
    # because unrelated words sat near the matched tokens. It supports the claim.
    passage = (
        "pgvector supports HNSW indexes. Inner product: CREATE INDEX ON items USING "
        "hnsw (embedding vector_ip_ops); cosine distance and L2 are documented the same way."
    )
    assert classify_stance(CLAIM, passage) == "supports"


def test_negation_must_precede_the_claim_term() -> None:
    # "no data" is not a denial of the claim; the cue has to sit before the term.
    passage = (
        "There is no data loss reported for pgvector supports HNSW indexes in "
        "this benchmark, and the extension documents both index types in detail."
    )
    assert classify_stance(CLAIM, passage) == "supports"


def test_cue_about_something_else_is_not_a_contradiction() -> None:
    # Real false positive from the corpus: "no longer fits maintenance_work_mem"
    # sits near the word hnsw in unpunctuated PDF text, but says nothing about
    # whether HNSW is supported.
    passage = (
        "Use set local inside a transaction begin set local hnsw ef_search select commit "
        "index build time indexes build significantly faster when the graph no longer fits "
        "maintenance_work_mem notice pgvector supports HNSW indexes."
    )
    assert classify_stance(CLAIM, passage) == "supports"


def test_counts_separate_support_from_contradiction() -> None:
    evidence = [
        {"polarity": "supports"},
        {"polarity": "supports"},
        {"polarity": "contradicts"},
        {"polarity": "mentions"},
    ]
    assert counts(evidence) == (2, 1, 1)
