"""Probe: what does the gate decide, and why, for a few real queries?

Runs inside the service image: database, corpus statistics and the reranker, with
no HTTP in between. Prints per-query coverage and the abstain reason so a
regression can be read instead of inferred.

    python scripts/probe_gate.py "query one" "query two"
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_shared.rerank import (  # noqa: E402
    RerankConfig,
    lexical_coverage,
    rerank,
    support_tokens,
)
from research_shared.term_stats import corpus_term_stats, idf_weights  # noqa: E402

QUERIES = [
    "What did cycle 039 decide about loading the portfolio into the knowledge graph?",
    "How many lifecycle states does a Drake slice have?",
    "When did Saimon move off Heroku?",
    "What is the carbon to nitrogen ratio for compost?",
    "What temperature should sous vide salmon be cooked at?",
]


async def main() -> int:
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    config = RerankConfig()
    for query in sys.argv[1:] or QUERIES:
        tokens = support_tokens(query)
        rows = await conn.fetch(
            "SELECT id, title, body, 0.9::float8 AS similarity FROM knowledge_graph_nodes"
            " WHERE body ILIKE '%' || $1 || '%' LIMIT 12",
            sorted(tokens)[0] if tokens else query,
        )
        candidates = [dict(row) for row in rows]
        df, size = await corpus_term_stats(conn, tokens)
        outcome = rerank(query, candidates, config, corpus_df=df, corpus_size=size)
        passages = [c["body"] for c in candidates]
        plain = max((lexical_coverage(query, p) for p in passages), default=0.0)
        folded = {t: df.get(t, 0) for t in tokens}
        weights = idf_weights(folded, size, tokens)
        weighted = max(
            (lexical_coverage(query, p, weights=weights) for p in passages), default=0.0
        )
        print(
            f"\n{query[:70]}\n  candidates={len(candidates)} df={folded}"
            f"\n  coverage plain={plain:.2f} weighted={weighted:.2f}"
            f" reason={outcome.abstain_reason} fired={outcome.fail_safe_fired}"
            f" top={outcome.top_score:.3f}"
        )
    await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
