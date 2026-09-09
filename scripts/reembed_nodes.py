#!/usr/bin/env python3
"""One-shot re-embed script for knowledge graph nodes (SAIMON-EMBEDDING-LOCAL-1).

Migrates ``knowledge_graph_nodes.embedding`` from ``VECTOR(1536)`` to
``VECTOR(768)`` and re-embeds existing nodes with the local
``nomic-embed-text`` model.

Run on dev/staging only — the PROD schema migration and prod model download
are operator-gated.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ALTER_SQL = (
    "ALTER TABLE knowledge_graph_nodes "
    "ALTER COLUMN embedding TYPE VECTOR(768)"
)


async def migrate_schema(pool) -> None:
    """ALTER the embedding column to VECTOR(768)."""
    await pool.execute(ALTER_SQL)


async def reembed_nodes(pool, *, all_nodes: bool = False) -> int:
    """Re-embed nodes; returns the number of rows updated."""
    from research_shared.embedding import EmbeddingConfig, embed_local

    cfg = EmbeddingConfig.from_env()
    where = "" if all_nodes else "WHERE embedding IS NULL"
    rows = await pool.fetch(f"SELECT id, body FROM knowledge_graph_nodes {where}")
    updated = 0
    for row in rows:
        vector = embed_local(
            row["body"] or "", cfg.model, cfg.dimensions, cfg.model_path or None
        )
        if vector is None:
            continue
        await pool.execute(
            "UPDATE knowledge_graph_nodes "
            "SET embedding = $1, updated_at = now() WHERE id = $2",
            str(vector),
            row["id"],
        )
        updated += 1
    return updated


async def run() -> int:
    parser = argparse.ArgumentParser(description="Re-embed knowledge graph nodes")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="run the ALTER COLUMN VECTOR(768) migration first",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-embed all nodes, not only rows with NULL embeddings",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    from research_shared.db import DatabaseConfig, DatabasePool

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    if args.migrate:
        await migrate_schema(pool)
        print("schema migrated: embedding VECTOR(768)")

    updated = await reembed_nodes(pool, all_nodes=args.all)
    print(f"re-embedded {updated} nodes")
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
