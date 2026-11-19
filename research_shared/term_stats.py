"""Corpus-level statistics for the coverage gate.

The gate measures how much of a query a passage covers. Counting matched tokens
treats every token as equally informative, which is why "When did Saimon move off
Heroku?" cleared it: `saimon` matched, `heroku` counted the same as `saimon`, and
the passage never had to account for a word that appears nowhere in the corpus.

Inverse document frequency fixes the arithmetic. A term in every chunk carries
almost no weight; a term in none of them carries the most, and its absence is
what should stop the answer. Document frequency is cached in a table so the count
runs once per term rather than once per query.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from typing import Any

LOGGER = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS corpus_term_df (
    term text PRIMARY KEY,
    df integer NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now()
)
"""

COUNT_DF_SQL = """
SELECT count(*) AS df
FROM knowledge_graph_nodes
WHERE body ~* ('\\m' || $1 || '\\M')
"""

COUNT_CHUNKS_SQL = "SELECT count(*) AS n FROM knowledge_graph_nodes"

_lookup_cache: dict[str, int] = {}


async def _ensure_table(pool: Any) -> bool:
    try:
        await pool.execute(CREATE_TABLE_SQL)
        return True
    except Exception:  # noqa: BLE001 - the gate has a fallback without statistics
        LOGGER.warning("corpus_term_df unavailable; coverage gate runs unweighted")
        return False


async def corpus_term_stats(
    pool: Any, terms: Iterable[str], *, corpus_size: int | None = None
) -> tuple[dict[str, int], int | None]:
    """Return ``({term: document_frequency}, corpus_size)`` for *terms*.

    A term absent from the corpus is returned with df 0 — that is the signal the
    gate needs, and it is cached so the count is not repeated for every query.
    """
    wanted = sorted({term.strip().lower() for term in terms if term and term.strip()})
    if not wanted or pool is None:
        return {}, corpus_size

    # A missing cache costs latency, not correctness. Counting every query is
    # slow; returning nothing because the cache table could not be created would
    # silently disable the weighting while looking like it worked.
    cache_ok = await _ensure_table(pool)

    known: dict[str, int] = {}
    missing: list[str] = []
    for term in wanted:
        if term in _lookup_cache:
            known[term] = _lookup_cache[term]
        else:
            missing.append(term)

    if missing and cache_ok:
        try:
            rows = await pool.fetch(
                "SELECT term, df FROM corpus_term_df WHERE term = ANY($1::text[])",
                missing,
            )
            for row in rows:
                known[row["term"]] = int(row["df"])
                _lookup_cache[row["term"]] = int(row["df"])
            missing = [term for term in missing if term not in known]
        except Exception:  # noqa: BLE001
            LOGGER.warning("corpus_term_df read failed; counting directly")
            missing = [term for term in missing if term not in known]

    if missing:
        try:
            row = await pool.fetchrow(COUNT_CHUNKS_SQL)
            corpus_size = int(row["n"]) if row else corpus_size
        except Exception:  # noqa: BLE001
            LOGGER.warning("chunk count unavailable; idf uses the stored size")
        for term in missing:
            try:
                counted = await pool.fetchrow(COUNT_DF_SQL, term)
                df = int(counted["df"]) if counted else 0
            except Exception:  # noqa: BLE001
                LOGGER.warning("document frequency for %r failed", term)
                continue
            known[term] = df
            _lookup_cache[term] = df
            if not cache_ok:
                continue
            try:
                await pool.execute(
                    "INSERT INTO corpus_term_df (term, df) VALUES ($1, $2) "
                    "ON CONFLICT (term) DO UPDATE SET df = EXCLUDED.df,"
                    " computed_at = now()",
                    term,
                    df,
                )
            except Exception:  # noqa: BLE001
                LOGGER.warning("could not cache document frequency for %r", term)

    return known, corpus_size


def idf_weights(
    document_frequency: dict[str, int], corpus_size: int | None, terms: Iterable[str]
) -> dict[str, float]:
    """Weight each term by how rare it is. Absent terms get the highest weight.

    ``log((N + 1) / (df + 1)) + 1`` keeps a term that appears everywhere at 1.0
    rather than 0.0, so coverage never divides by zero and a query made entirely
    of common words still has an arithmetic meaning.
    """
    size = max(int(corpus_size or 0), 1)
    weights: dict[str, float] = {}
    for term in terms:
        df = int(document_frequency.get(term, 0))
        weights[term] = math.log((size + 1) / (df + 1)) + 1.0
    return weights
