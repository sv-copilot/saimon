"""The floor is a similarity question, not a blend question (#361).

Measured defect: a passage with cosine 0.774 and weak lexical overlap scored
0.43 on the 0.5/0.5 blend and the gate abstained. Three of twenty-five benchmark
queries were refused for this reason.
"""

from __future__ import annotations

from research_shared.rerank import RerankConfig, gate_decision, rerank

CFG = RerankConfig()


def _candidate(score: float, semantic: float, unit: str) -> dict:
    return {"relevance_score": score, "semantic_score": semantic, "unit_id": unit, "title": unit}


def test_high_similarity_low_lexical_does_not_abstain() -> None:
    # cosine 0.774, blend 0.43 — the benchmark's false abstention. Lexical
    # support is present, so only the floor could have refused it.
    # Clear margin over the runner-up, so only the floor is in question.
    scored = [_candidate(0.78, 0.774, "doc-a"), _candidate(0.45, 0.40, "doc-b")]
    abstain, top, _ = gate_decision(scored, CFG, True, gate_score=0.774)
    assert abstain is False
    assert top == 0.774


def test_low_similarity_still_abstains() -> None:
    scored = [_candidate(0.30, 0.31, "doc-a"), _candidate(0.29, 0.30, "doc-b")]
    abstain, top, _ = gate_decision(scored, CFG, True, gate_score=0.31)
    assert abstain is True
    assert top == 0.31


def test_rerank_uses_semantic_for_the_floor() -> None:
    candidates = [
        {"id": "1", "title": "a", "body": "pgvector hnsw indexes support cosine distance here", "similarity": 0.774, "unit_id": "a"},
        {"id": "2", "title": "b", "body": "other text about hnsw indexes and pgvector", "similarity": 0.70, "unit_id": "b"},
    ]
    outcome = rerank("pgvector hnsw indexes", candidates, CFG)
    assert outcome.fail_safe_fired is False
    assert outcome.ranked
    assert outcome.top_score >= 0.62
