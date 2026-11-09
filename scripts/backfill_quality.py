#!/usr/bin/env python3
"""Backfill quality scores for claims and their source documents (#255).

Persisted in node metadata, not new columns: `schema.sql` only runs on a fresh
database, so a column would be missing on the live cluster at deploy time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLAIM_SQL = """
SELECT n.id, n.title, n.body, n.metadata, n.unit_id,
       f.value_numeric, f.unit, f.date_start,
       o.verification_status, o.confidence_0_1,
       d.id AS doc_id
FROM knowledge_graph_nodes n
LEFT JOIN observation_facts f ON f.node_id = n.id
LEFT JOIN observations o ON o.unit_id = n.unit_id
LEFT JOIN LATERAL (
    SELECT tgt.id
    FROM knowledge_graph_edges e
    JOIN knowledge_graph_nodes chunk ON chunk.id = e.target_id
    JOIN knowledge_graph_nodes tgt ON tgt.id = NULLIF(chunk.metadata->>'part_of', '')::uuid
    WHERE e.source_id = n.id AND e.relation_type = 'derived_from'
    LIMIT 1
) d ON TRUE
WHERE n.content_type = 'claim'
"""

LEDGER_SQL = """
SELECT claim_hash, verdict, confidence, created_at
FROM verification_ledger
ORDER BY created_at DESC
"""

RELATION_SQL = """
SELECT source_id, target_id, relation_type
FROM knowledge_graph_edges
WHERE relation_type IN ('supports', 'contradicts')
"""

DOC_SQL = "SELECT id, metadata, title FROM knowledge_graph_nodes WHERE content_type = 'fulltext_document'"

# Source class -> reputation tier. Kept coarse on purpose: a tier nobody can
# justify is worse than `unknown`.
TIER_BY_CLASS = {
    "journal_article": "A", "government_report": "A", "dataset": "A", "document": "A",
    "report": "B", "news": "B", "press_release": "B",
    "blog": "C", "social": "C", "forum_post": "C",
}


def _meta(row) -> dict:
    raw = row.get("metadata")
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


async def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="write scores even when inputs are mostly defaults")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from research_shared.db import DatabaseConfig, DatabasePool
    from research_shared.primacy import source_class_from_host
    from research_shared.quality import (
        QUALITY_VERSION,
        claim_extraction_confidence,
        extraction_score,
        is_scoreable,
        observation_quality,
        relation_balance,
        reputation_score,
        source_quality,
        structure_score,
        verification_score,
    )

    pool = DatabasePool(DatabaseConfig(database_url=db_url))
    await pool.fetch("SELECT 1")

    supporting: Counter[str] = Counter()
    dissenting: Counter[str] = Counter()
    for edge in await pool.fetch(RELATION_SQL):
        if edge["relation_type"] == "supports":
            supporting[edge["source_id"]] += 1
        else:
            dissenting[edge["source_id"]] += 1

    # Verification input comes from the ledger first (#271), then from the legacy
    # observations join. Latest verdict wins.
    latest: dict[str, tuple[str, float]] = {}
    try:
        for row in await pool.fetch(LEDGER_SQL):
            latest.setdefault(row["claim_hash"], (row["verdict"], float(row["confidence"] or 0.0)))
    except Exception:  # noqa: BLE001 — ledger absent on an older schema; scoring stays blind, not crashed
        latest = {}

    claims = await pool.fetch(CLAIM_SQL)
    from research_shared.provenance import claim_hash as _claim_hash
    for claim in claims:
        # Truncate exactly as the verify caller does, or the hash will not match
        # the ledger row for long claims.
        text = f"{claim.get('title') or ''}. {claim.get('body') or ''}".strip()[:4000]
        key = _claim_hash(text)
        if key in latest:
            claim["verification_status"], claim["confidence_0_1"] = latest[key]
    print(f"{len(claims)} claim(s)", flush=True)

    total = max(len(claims), 1)
    with_verification = sum(1 for c in claims if c.get("verification_status"))
    with_extraction = sum(
        1 for c in claims
        if claim_extraction_confidence(
            row_confidence=c.get("confidence_0_1"), metadata=_meta(c)
        ) is not None
    )
    ok, reason = is_scoreable(
        verification_coverage=with_verification / total,
        extraction_coverage=with_extraction / total,
    )
    coverage = {
        "claims": len(claims),
        "verification_inputs": f"{with_verification} ({with_verification * 100 // total}%)",
        "extraction_inputs": f"{with_extraction} ({with_extraction * 100 // total}%)",
        "scoreable": ok,
        "reason": reason,
    }
    if not ok and not args.force:
        print(json.dumps({**coverage, "refused": "insufficient real inputs — a score built from "
                                                  "defaults is not a measurement"}, indent=2))
        await pool.close()
        return 3

    per_doc: dict[str, list[float]] = defaultdict(list)
    doc_health: dict[str, list[float]] = defaultdict(list)
    scores: Counter[str] = Counter()
    written = 0

    for claim in claims:
        meta = _meta(claim)
        doi = meta.get("doi") or ""
        host = doi.split("url:", 1)[1] if doi.startswith("url:") else doi
        tier = TIER_BY_CLASS.get(source_class_from_host(host), "unknown")

        structure = structure_score(
            has_value=claim.get("value_numeric") is not None,
            has_date=claim.get("date_start") is not None,
            has_unit=bool(claim.get("unit")),
        )
        # Claims store the extractor's own confidence under `confidence`; looking
        # only for `extraction_confidence` made every score default its heaviest
        # component. Measured after the fix: 8,520 of 8,520 claims have it.
        extraction = extraction_score(claim_extraction_confidence(
            row_confidence=claim.get("confidence_0_1"), metadata=meta
        ))
        verification = verification_score(claim.get("verification_status"))
        score, breakdown = observation_quality(
            extraction=extraction, verification=verification,
            reputation=reputation_score(tier), structure=structure,
        )
        scores[f"{score:.1f}"] += 1

        if claim.get("doc_id"):
            per_doc[claim["doc_id"]].append(score)
            doc_health[claim["doc_id"]].append(verification)

        if args.dry_run:
            continue
        meta.update({
            "quality_score": score, "quality_version": QUALITY_VERSION,
            "quality_breakdown": breakdown, "reputation_tier": tier,
        })
        await pool.execute(
            "UPDATE knowledge_graph_nodes SET metadata = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(meta), claim["id"],
        )
        written += 1

    docs_written = 0
    for doc in await pool.fetch(DOC_SQL):
        values = per_doc.get(doc["id"]) or []
        meta = _meta(doc)
        doi = meta.get("doi") or ""
        host = doi.split("url:", 1)[1] if doi.startswith("url:") else doi
        tier = TIER_BY_CLASS.get(source_class_from_host(host), "unknown")
        balance = relation_balance(
            sum(supporting.values()), sum(dissenting.values())
        )
        score, breakdown = source_quality(
            reputation=reputation_score(tier),
            mean_observation=(sum(values) / len(values)) if values else 0.45,
            verification_health=(sum(doc_health[doc["id"]]) / len(doc_health[doc["id"]]))
            if doc_health.get(doc["id"]) else 0.30,
            extraction_health=0.55,
            balance=balance,
        )
        if args.dry_run:
            continue
        meta.update({"source_quality_score": score, "quality_version": QUALITY_VERSION,
                     "source_quality_breakdown": breakdown})
        await pool.execute(
            "UPDATE knowledge_graph_nodes SET metadata = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps(meta), doc["id"],
        )
        docs_written += 1

    print(json.dumps({
        "claims": len(claims), "claims_written": written, "documents_written": docs_written,
        "dry_run": args.dry_run,
        "score_histogram": dict(sorted(scores.items())),
    }, indent=2))
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
