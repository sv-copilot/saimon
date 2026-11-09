#!/usr/bin/env python3
"""Backfill observation_facts for existing claims and observations (#272).

Idempotent: re-running recomputes the same rows from the same text. Prints a
coverage report rather than a bare count, because "12,000 rows written" says
nothing about whether the numbers are real.

Usage:
    DATABASE_URL=... python scripts/backfill_observation_facts.py --dry-run
    DATABASE_URL=... python scripts/backfill_observation_facts.py --limit 500
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

CONTENT_TYPES = ("claim", "observation")

UPSERT = """
INSERT INTO observation_facts (
    node_id, value_numeric, value_text, unit, date_start, date_end,
    date_base_unit, latitude, longitude, topic, confidence, reasons, parser_version
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13)
ON CONFLICT (node_id) DO UPDATE SET
    value_numeric = EXCLUDED.value_numeric,
    value_text = EXCLUDED.value_text,
    unit = EXCLUDED.unit,
    date_start = EXCLUDED.date_start,
    date_end = EXCLUDED.date_end,
    date_base_unit = EXCLUDED.date_base_unit,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    topic = EXCLUDED.topic,
    confidence = EXCLUDED.confidence,
    reasons = EXCLUDED.reasons,
    parser_version = EXCLUDED.parser_version,
    updated_at = now()
"""


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = every eligible node")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from research_shared.db import DatabaseConfig, DatabasePool
    from research_shared.facts import PARSER_VERSION, parse_fact

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    sql = (
        "SELECT id, title, body FROM knowledge_graph_nodes "
        "WHERE content_type = ANY($1) ORDER BY created_at"
    )
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    rows = await pool.fetch(sql, list(CONTENT_TYPES))
    print(f"{len(rows)} node(s) eligible", flush=True)

    written = 0
    coverage: Counter[str] = Counter()
    for row in rows:
        text = f"{row.get('title') or ''}. {row.get('body') or ''}".strip()
        fact = parse_fact(text)
        if fact.value_numeric is not None:
            coverage["value_numeric"] += 1
        if fact.date_start is not None:
            coverage["date_start"] += 1
        if fact.unit:
            coverage[f"unit:{fact.unit}"] += 1
        if args.dry_run:
            continue
        await pool.execute(
            UPSERT,
            row["id"], fact.value_numeric, fact.value_text, fact.unit,
            fact.date_start, fact.date_end, fact.date_base_unit,
            fact.latitude, fact.longitude, fact.topic, fact.confidence,
            json.dumps(fact.reasons, sort_keys=True), PARSER_VERSION,
        )
        written += 1

    total = max(len(rows), 1)
    report = {
        "eligible": len(rows),
        "written": written,
        "dry_run": args.dry_run,
        "coverage": {k: f"{v} ({v * 100 // total}%)" for k, v in coverage.most_common()},
    }
    print(json.dumps(report, indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
