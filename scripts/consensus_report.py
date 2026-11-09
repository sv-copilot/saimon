#!/usr/bin/env python3
"""Report consensus, contradiction and silence across the corpus (#274).

Usage:
    DATABASE_URL=... python scripts/consensus_report.py --limit 500
    DATABASE_URL=... python scripts/consensus_report.py --seed <claim-id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RELATIONS_SQL = """
SELECT e.target_id, n.title, e.relation_type, e.weight, e.metadata
FROM knowledge_graph_edges e
JOIN knowledge_graph_nodes n ON n.id = e.target_id
WHERE e.source_id = $1 AND e.relation_type IN ('supports', 'contradicts', 'related')
"""

SEEDS_SQL = """
SELECT DISTINCT source_id
FROM knowledge_graph_edges
WHERE relation_type IN ('supports', 'contradicts')
LIMIT $1
"""


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", help="one claim id")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from research_shared.consensus import build_view, summarise
    from research_shared.db import DatabaseConfig, DatabasePool

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    if args.seed:
        seeds = [{"source_id": args.seed}]
    else:
        seeds = await pool.fetch(SEEDS_SQL, args.limit)

    views = []
    for seed in seeds:
        relations = [
            dict(row) for row in await pool.fetch(RELATIONS_SQL, seed["source_id"])
        ]
        views.append(build_view(str(seed["source_id"]), relations))

    print(json.dumps(summarise(views), indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
