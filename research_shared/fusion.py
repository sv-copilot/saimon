"""Reciprocal-rank fusion for hybrid retrieval (SAIMON-HYBRID-RRF-1).

Vector and lexical results are not comparable on score: cosine similarity lives
in [0, 1], BM25 is unbounded and — as found on 2026-11-08 — its normalised form
shifts when the corpus grows, so a query can fall out of the answer band because
three documents were added. RRF fuses by RANK, which is scale-free:

    score(d) = sum over lists of 1 / (k + rank(d))

It also fixes a structural gap in the old merge: vector results were taken first
and truncated at the limit, so lexical-only hits were discarded whenever the
vector path filled the quota.
"""

from __future__ import annotations

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = DEFAULT_RRF_K,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists into one ordered list of (id, score).

    Deterministic: ties break by best rank in any list, then lexicographically by
    id, so two runs over the same input always produce the same order.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for ranked in ranked_lists:
        seen: set[str] = set()
        for index, item_id in enumerate(ranked):
            key = str(item_id)
            if key in seen:  # a list may contain duplicates; first rank wins
                continue
            seen.add(key)
            rank = index + 1
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            best_rank[key] = min(best_rank.get(key, rank), rank)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], best_rank[item[0]], item[0]))
    fused = [(item_id, round(score, 8)) for item_id, score in ordered]
    return fused[:limit] if limit is not None else fused
