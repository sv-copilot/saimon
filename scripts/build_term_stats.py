#!/usr/bin/env python3
"""Precompute document frequency for the whole corpus vocabulary.

The gate asks for a handful of terms per query. Counting them at query time means
a regex scan over every chunk per term, which took the median query from 360 ms to
1,105 ms. One pass over the corpus fills the cache instead, so queries only read.

    python scripts/build_term_stats.py [--min-df 2]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_shared.rerank import content_tokens  # noqa: E402


async def main_async(args: argparse.Namespace) -> int:
    import asyncpg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS corpus_term_df ("
            " term text PRIMARY KEY, df integer NOT NULL,"
            " computed_at timestamptz NOT NULL DEFAULT now())"
        )
        bodies = [
            row["body"]
            for row in await conn.fetch(
                "SELECT body FROM knowledge_graph_nodes WHERE body IS NOT NULL"
            )
        ]
        print(f"chunks: {len(bodies)}", file=sys.stderr)

        counts: Counter[str] = Counter()
        for body in bodies:
            counts.update(set(content_tokens(body)))

        rows = [(term, df) for term, df in counts.items() if df >= args.min_df]
        print(f"terms: {len(rows)}", file=sys.stderr)

        for start in range(0, len(rows), args.batch):
            batch = rows[start : start + args.batch]
            await conn.executemany(
                "INSERT INTO corpus_term_df (term, df) VALUES ($1, $2)"
                " ON CONFLICT (term) DO UPDATE SET df = EXCLUDED.df,"
                " computed_at = now()",
                batch,
            )
            print(f"  {start + len(batch)}/{len(rows)}", file=sys.stderr)

        total = await conn.fetchval("SELECT count(*) FROM corpus_term_df")
        print(f"corpus_term_df rows: {total}")
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-df", type=int, default=2)
    parser.add_argument("--batch", type=int, default=5000)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
