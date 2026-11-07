"""rerank.py — deterministic passage-level relevance scoring.

Saimon's ``search`` returns raw adapter hits directly into ``generate`` and
``verify``.  This module adds the retrieval-layer quality gate: score candidate
passages against the query, keep the top-K by relevance (not adapter order),
and flag ``no_strong_evidence`` when nothing clears ``min_relevance``.

Scoring is deterministic and dependency-free: a BM25-style lexical term score
combined with cosine embedding similarity.  A flash-model cross-encoder is a
follow-up, not this module.

The module has no imports outside the standard library so it can be unit-tested
without a DB, without fastembed, and without any network access.  Embeddings are
supplied by an optional injectable ``embed_fn``.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

DEFAULT_MIN_RELEVANCE = 0.62
DEFAULT_MIN_MARGIN = 0.08
DEFAULT_TOP_K = 10
DEFAULT_MAX_REQUERY = 1
DEFAULT_LEXICAL_WEIGHT = 0.5
DEFAULT_SEMANTIC_WEIGHT = 0.5

# BM25 free parameters (standard defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "to", "was",
        "were", "what", "with",
    }
)


@dataclass
class RerankConfig:
    """Configuration for the passage-level reranker."""

    min_relevance: float = DEFAULT_MIN_RELEVANCE
    min_margin: float = DEFAULT_MIN_MARGIN
    top_k: int = DEFAULT_TOP_K
    max_requery: int = DEFAULT_MAX_REQUERY
    lexical_weight: float = DEFAULT_LEXICAL_WEIGHT
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT

    @classmethod
    def from_env(cls) -> RerankConfig:
        """Build config from ``SAIMON_RERANK_*`` environment variables."""
        return cls(
            min_relevance=float(
                os.getenv("SAIMON_RERANK_MIN_RELEVANCE", str(DEFAULT_MIN_RELEVANCE))
            ),
            min_margin=float(
                os.getenv("SAIMON_RERANK_MIN_MARGIN", str(DEFAULT_MIN_MARGIN))
            ),
            top_k=int(os.getenv("SAIMON_RERANK_TOP_K", str(DEFAULT_TOP_K))),
            max_requery=int(
                os.getenv("SAIMON_RERANK_MAX_REQUERY", str(DEFAULT_MAX_REQUERY))
            ),
            lexical_weight=float(
                os.getenv("SAIMON_RERANK_LEXICAL_WEIGHT", str(DEFAULT_LEXICAL_WEIGHT))
            ),
            semantic_weight=float(
                os.getenv("SAIMON_RERANK_SEMANTIC_WEIGHT", str(DEFAULT_SEMANTIC_WEIGHT))
            ),
        )


@dataclass
class RerankOutcome:
    """Result of reranking a candidate set against a query."""

    ranked: list[dict[str, Any]]
    top_score: float
    second_score: float
    margin_gap: float
    candidate_count: int
    kept_count: int
    fail_safe_fired: bool


# ---------------------------------------------------------------------------
# tokenisation + BM25 lexical scoring
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Lowercase and split *text* into alphanumeric tokens."""
    return _TOKEN_RE.findall((text or "").lower())


def _passage_text(candidate: dict[str, Any]) -> str:
    """Return the searchable text for a candidate passage dict."""
    title = candidate.get("title") or ""
    body = candidate.get("body") or ""
    return f"{title}\n{body}".strip()


def bm25_scores(
    query: str,
    passages: list[str],
    *,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
) -> list[float]:
    """Compute BM25 lexical scores for *passages* against *query*.

    IDF is computed over the candidate passage set itself, so the scorer is
    deterministic and self-contained (no external corpus statistics required).
    """
    query_terms = tokenize(query)
    if not query_terms or not passages:
        return [0.0 for _ in passages]

    tokenized = [tokenize(p) for p in passages]
    n_passages = len(passages)
    avg_len = (sum(len(t) for t in tokenized) / n_passages) or 1.0

    document_freq: dict[str, int] = {}
    for term in query_terms:
        document_freq[term] = sum(1 for tokens in tokenized if term in tokens)

    scores: list[float] = []
    for tokens in tokenized:
        doc_len = len(tokens) or 1
        score = 0.0
        for term in query_terms:
            df = document_freq.get(term, 0)
            idf = math.log(1.0 + (n_passages - df + 0.5) / (df + 0.5))
            term_freq = tokens.count(term)
            if term_freq:
                score += idf * (
                    (term_freq * (k1 + 1.0))
                    / (term_freq + k1 * (1.0 - b + b * (doc_len / avg_len)))
                )
        scores.append(score)
    return scores


# ---------------------------------------------------------------------------
# cosine embedding similarity
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity between two vectors (0.0 for zero vectors)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# deterministic reformulation (fail-safe re-query)
# ---------------------------------------------------------------------------


def reformulate_query(query: str) -> str:
    """Return a deterministic, broadened reformulation of *query*.

    Strips common stopwords; if the result is unchanged (or empty) it appends a
    broadening term so the re-query always differs from the original.
    """
    original = (query or "").strip()
    keywords = [t for t in tokenize(original) if t not in _STOPWORDS]
    reformulated = " ".join(keywords) if keywords else original
    if not reformulated or reformulated == original.lower():
        reformulated = f"{original} overview"
    return reformulated


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------


def gate_decision(
    scored: list[dict[str, Any]], config: RerankConfig
) -> tuple[bool, float, float]:
    """Decide whether a scored candidate set must abstain.

    Two independent reasons to abstain, both needed:

    * **floor** - the top score is below ``config.min_relevance``.  The floor
      sits above the reranker's nonsense semantic-similarity baseline, so an
      unrelated query returns nothing instead of top-N noise.
    * **margin** - the top score clears the floor but is not far enough ahead of
      the runner-up.  A weak-but-real hit and noise can land in the same band
      (~0.6-0.7); the gap over the second-best is what separates them.

    Returns ``(abstain, top_score, margin_gap)``.  A single candidate is judged
    on the floor alone, because there is no runner-up to be ambiguous about.
    """
    if not scored:
        return True, 0.0, 0.0

    top_score = float(scored[0]["relevance_score"])
    second_score = float(scored[1]["relevance_score"]) if len(scored) > 1 else 0.0
    margin_gap = top_score - second_score

    if top_score < config.min_relevance:
        return True, top_score, margin_gap
    if len(scored) > 1 and margin_gap < config.min_margin:
        return True, top_score, margin_gap
    return False, top_score, margin_gap


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    config: RerankConfig | None = None,
    *,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    top_k: int | None = None,
) -> RerankOutcome:
    """Score *candidates* against *query* and return the ranked top-K.

    Each candidate keeps its original fields and gains ``relevance_score``,
    ``lexical_score`` and ``semantic_score``.  Candidates are sorted descending
    by ``relevance_score``.  When no candidate clears ``config.min_relevance``
    the outcome carries ``fail_safe_fired=True`` and an empty ``ranked`` list.
    """
    cfg = config or RerankConfig()
    k = top_k if top_k is not None else cfg.top_k

    passages = [_passage_text(c) for c in candidates]
    lexical_raw = bm25_scores(query, passages)
    max_lexical = max(lexical_raw) if lexical_raw else 0.0

    query_embedding: list[float] | None = None
    if embed_fn is not None:
        needs_embedding = any(c.get("similarity") is None for c in candidates)
        if needs_embedding:
            query_embedding = embed_fn(query)

    scored: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        lexical_norm = (
            (lexical_raw[index] / max_lexical) if max_lexical > 0.0 else 0.0
        )

        similarity = candidate.get("similarity")
        if similarity is None and embed_fn is not None and query_embedding is not None:
            passage_embedding = embed_fn(_passage_text(candidate))
            if passage_embedding is not None:
                similarity = cosine_similarity(query_embedding, passage_embedding)

        semantic = 0.0
        if similarity is not None:
            semantic = max(0.0, min(1.0, float(similarity)))

        final_score = (
            cfg.lexical_weight * lexical_norm + cfg.semantic_weight * semantic
        )

        item = dict(candidate)
        item["relevance_score"] = round(final_score, 6)
        item["lexical_score"] = round(lexical_norm, 6)
        item["semantic_score"] = round(semantic, 6)
        scored.append(item)

    scored.sort(key=lambda r: r["relevance_score"], reverse=True)
    fail_safe_fired, top_score, margin_gap = gate_decision(scored, cfg)
    second_score = float(scored[1]["relevance_score"]) if len(scored) > 1 else 0.0
    ranked = [] if fail_safe_fired else scored[:k]

    return RerankOutcome(
        ranked=ranked,
        top_score=top_score,
        second_score=second_score,
        margin_gap=margin_gap,
        candidate_count=len(candidates),
        kept_count=len(ranked),
        fail_safe_fired=fail_safe_fired,
    )
