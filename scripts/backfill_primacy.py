#!/usr/bin/env python3
"""Backfill primacy distance onto claim and observation nodes (#254).

No schema change: primacy lands in node `metadata` as
`primacy_distance_score` / `primacy_tier` / `primacy_version` /
`primacy_breakdown` / `primacy_scored_at`. That is deliberate — `schema.sql`
only runs on a fresh database, so a new column would be missing on the live
cluster the moment the code deployed (the #251/#252 lesson).

Lineage model for Saimon: a claim derived from a document chunk sits one hop
from the document, and the document is the direct anchor. A claim with no
document behind it has no path, which scores the flat 0.58 penalty rather than
pretending to be direct.
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

CANDIDATE_SQL = """
SELECT n.id, n.title, n.body, n.content_type, n.metadata,
       COALESCE(d.doc_doi, u.metadata->>'doi') AS doc_doi,
       COALESCE(d.doc_title, u.title) AS doc_title,
       o.verification_status AS obs_status,
       o.confidence_0_1      AS obs_confidence
FROM knowledge_graph_nodes n
LEFT JOIN LATERAL (
    SELECT tgt.id,
           tgt.metadata->>'doi' AS doc_doi,
           tgt.title            AS doc_title
    FROM knowledge_graph_edges e
    JOIN knowledge_graph_nodes src_chunk ON src_chunk.id = e.target_id
    JOIN knowledge_graph_nodes tgt
      ON tgt.id = NULLIF(src_chunk.metadata->>'part_of', '')::uuid
    WHERE e.source_id = n.id AND e.relation_type = 'derived_from'
    LIMIT 1
) d ON TRUE
LEFT JOIN knowledge_graph_nodes u ON u.id = n.unit_id
LEFT JOIN observations o ON o.unit_id = n.unit_id
WHERE n.content_type = ANY($1)
ORDER BY n.created_at
"""


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from research_shared.db import DatabaseConfig, DatabasePool
    from research_shared.primacy import compute_primacy, source_class_from_host

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    sql = CANDIDATE_SQL
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    rows = await pool.fetch(sql, ["claim", "observation"])
    print(f"{len(rows)} node(s) eligible", flush=True)

    tiers: Counter[str] = Counter()
    written = 0
    for row in rows:
        doi = row.get("doc_doi") or ""
        host = doi.split("url:", 1)[1] if doi.startswith("url:") else doi
        source_class = source_class_from_host(host) if host else "unknown"
        hops = 1 if row.get("doc_doi") else None

        score, tier, breakdown = compute_primacy(
            text=f"{row.get('title') or ''}. {row.get('body') or ''}",
            source_class=source_class,
            hops=hops,
            verification_status=row.get("obs_status"),
            confidence=row.get("obs_confidence"),
            has_context=bool(row.get("doc_doi")) or row.get("content_type") == "observation",
        )
        tiers[tier] += 1
        if args.dry_run:
            continue

        raw = row.get("metadata")
        metadata = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        metadata.update({
            "primacy_distance_score": score,
            "primacy_tier": tier,
            "primacy_version": breakdown["version"],
            "primacy_breakdown": breakdown,
            "primacy_scored_at": "now()",
        })
        await pool.execute(
            "UPDATE knowledge_graph_nodes SET metadata = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(metadata), row["id"],
        )
        written += 1

    total = max(len(rows), 1)
    print(json.dumps({
        "eligible": len(rows),
        "written": written,
        "dry_run": args.dry_run,
        "tiers": {tier: f"{count} ({count * 100 // total}%)" for tier, count in tiers.most_common()},
    }, indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
