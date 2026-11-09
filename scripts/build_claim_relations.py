#!/usr/bin/env python3
"""Build typed relations between claims (#253), clustered by topic first.

Topic is the source document: claims derived from the same document are talking
about the same thing far more reliably than an embedding threshold, and it bounds
the work — 8,520 claims pairwise is 36M comparisons.

Within a topic cluster, each claim is compared with its nearest neighbours
(similarity), then the structured facts decide:

* agreeing numbers within 10% over overlapping dates  -> `supports`
* diverging numbers beyond 25% over overlapping dates -> `contradicts`
* otherwise semantic similarity >= 0.86                -> `related`

Idempotent: existing triples are skipped, self-edges are impossible by
construction (``a < b``), and the direction is recorded in metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RELATED_SIMILARITY = 0.86

PAIR_SQL = """
WITH c AS (
    SELECT n.id, tgt.id AS doc_id, n.embedding
    FROM knowledge_graph_nodes n
    JOIN knowledge_graph_edges e
      ON e.source_id = n.id AND e.relation_type = 'derived_from'
    JOIN knowledge_graph_nodes chunk ON chunk.id = e.target_id
    JOIN knowledge_graph_nodes tgt
      ON tgt.id = NULLIF(chunk.metadata->>'part_of', '')::uuid
    WHERE n.content_type = 'claim' AND n.embedding IS NOT NULL
)
SELECT DISTINCT a.id AS a_id, b.id AS b_id,
       1 - (a.embedding <=> b.embedding) AS similarity
FROM c a
JOIN LATERAL (
    SELECT b2.id, b2.embedding
    FROM c b2
    WHERE b2.doc_id = a.doc_id AND b2.id <> a.id
    ORDER BY a.embedding <=> b2.embedding
    LIMIT $1
) b ON TRUE
WHERE a.id < b.id
"""

FACTS_SQL = """
SELECT f.node_id, f.value_numeric, f.unit, f.date_start, f.date_end,
       n.title, n.body
FROM observation_facts f
JOIN knowledge_graph_nodes n ON n.id = f.node_id
"""

INSERT_SQL = """
INSERT INTO knowledge_graph_edges (source_id, target_id, relation_type, weight, metadata)
VALUES ($1, $2, $3, $4, $5::jsonb)
ON CONFLICT (source_id, target_id, relation_type) DO NOTHING
"""


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neighbours", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from research_shared.db import DatabaseConfig, DatabasePool
    from research_shared.relations import RELATION_VERSION, compare

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    pairs = await pool.fetch(PAIR_SQL, args.neighbours)
    facts = {row["node_id"]: row for row in await pool.fetch(FACTS_SQL)}
    print(f"{len(pairs)} candidate pair(s) within topic clusters, {len(facts)} fact row(s)", flush=True)

    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    written = 0
    for pair in pairs:
        a_id, b_id, similarity = pair["a_id"], pair["b_id"], float(pair["similarity"])
        a, b = facts.get(a_id), facts.get(b_id)
        decision = compare(
            similarity=similarity,
            a_text=f"{(a or {}).get('title') or ''} {(a or {}).get('body') or ''}",
            b_text=f"{(b or {}).get('title') or ''} {(b or {}).get('body') or ''}",
            a_value=(a or {}).get("value_numeric"), a_unit=(a or {}).get("unit"),
            a_start=(a or {}).get("date_start"), a_end=(a or {}).get("date_end"),
            b_value=(b or {}).get("value_numeric"), b_unit=(b or {}).get("unit"),
            b_start=(b or {}).get("date_start"), b_end=(b or {}).get("date_end"),
        )
        if decision.relation:
            relation, strength, reason = decision.relation, decision.strength, decision.reason
        elif similarity >= RELATED_SIMILARITY:
            relation, strength, reason = "related", round(similarity, 4), "semantic_similarity"
        else:
            skipped[decision.reason] += 1
            continue

        counts[relation] += 1
        if args.dry_run:
            continue
        await pool.execute(
            INSERT_SQL, a_id, b_id, relation, strength,
            json.dumps({"reason": reason, "version": RELATION_VERSION,
                        "similarity": round(similarity, 4), "direction": "a_to_b"}),
        )
        written += 1

    print(json.dumps({
        "pairs": len(pairs),
        "written": written,
        "dry_run": args.dry_run,
        "relations": dict(counts.most_common()),
        "skipped_reasons": dict(skipped.most_common(6)),
    }, indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
