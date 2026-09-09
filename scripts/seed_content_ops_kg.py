#!/usr/bin/env python3
"""Seed the content-ops knowledge graph (SAIMON-CONTENT-OPS-KG-SEED-1).

Loads the canonical content-ops node types (profile_fact/source/topic/
lifecycle_stage/post) and the canonical anchors (profile facts, theory
citations, the 1-11 lifecycle spine, and topic entities) into the shared
PostgreSQL knowledge graph.  Re-runnable and idempotent — node ids are stable
(UUIDv5) and inserts use ON CONFLICT DO NOTHING, so a re-run never duplicates.

Optionally writes the stable-id seed manifest to JSON (default:
scripts/content_ops_seed_manifest.json).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the content-ops knowledge graph"
    )
    parser.add_argument(
        "--manifest-out",
        default=str(Path(__file__).resolve().parent / "content_ops_seed_manifest.json"),
        help="path to write the stable-id seed manifest JSON",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    from research_shared.content_ops_seed import build_manifest, seed_content_ops_kg
    from research_shared.db import DatabaseConfig, DatabasePool

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    result = await seed_content_ops_kg(pool)
    print(json.dumps(result, indent=2))

    manifest = build_manifest()
    await asyncio.to_thread(_write_manifest, args.manifest_out, manifest)
    print(f"manifest written to {args.manifest_out}")

    await pool.close()
    return 0


def _write_manifest(path: str, manifest: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
