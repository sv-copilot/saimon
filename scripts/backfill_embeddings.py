#!/usr/bin/env python3
"""Backfill NULL embeddings for knowledge-graph nodes (SAIMON-EMBEDDING-BACKFILL-1).

Embeds the ``title`` + ``body`` of every node whose ``embedding`` is NULL using
the local ``nomic-embed-text`` (768-dim) model. Idempotent and re-runnable:
already-embedded nodes are never selected, and a failed embed is logged and
skipped without aborting the batch.

Run on dev/staging only — the PROD run is operator-gated.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run() -> int:
    parser = argparse.ArgumentParser(description="Backfill NULL node embeddings")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="maximum number of nodes to backfill per run",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    from research_shared.db import DatabaseConfig, DatabasePool
    from research_shared.embedding import backfill_null_embeddings

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    result = await backfill_null_embeddings(pool, limit=args.limit)
    print(
        f"backfill complete: embedded={result['embedded']} "
        f"failed={result['failed']}"
    )
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
