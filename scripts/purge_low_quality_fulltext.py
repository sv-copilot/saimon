#!/usr/bin/env python3
"""One-shot idempotent purge of low-quality full-text nodes (SAIMON-OCR-CLEANUP-1, #198).

Deletes ``fulltext_chunk`` nodes whose body fails the #196 quality gate, plus
their orphaned ``fulltext_document`` nodes, ``shadow_sources_cache`` rows, and
S3 objects.  Re-runnable — the second run is a no-op.

Run on staging only (prod is operator-gated).

Usage:
    DATABASE_URL=postgresql://... python3 scripts/purge_low_quality_fulltext.py
    DATABASE_URL=postgresql://... python3 scripts/purge_low_quality_fulltext.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_shared.fulltext_purge import purge_low_quality_fulltext
from research_shared.s3_storage import S3Storage


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without deleting anything",
    )
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    from research_shared.db import DatabaseConfig, DatabasePool

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    storage = S3Storage.from_env()
    summary = await purge_low_quality_fulltext(
        pool, storage if storage.configured else None, dry_run=args.dry_run
    )
    print(json.dumps(summary, indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
