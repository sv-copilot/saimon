#!/usr/bin/env python3
"""Extract falsifiable claims from fulltext chunks into the knowledge graph.

Each claim becomes a ``claim`` node carrying provenance (source document, source
chunk, extractor, confidence) with a ``derived_from`` edge back to its chunk, so
an answer can be traced to a sentence in a real document.

Idempotent: a claim is keyed by a hash of its normalised text, so re-running
never duplicates. Fail-closed: a chunk whose extraction returns nothing is
skipped rather than recorded as "no claims".

Usage (inside a container that has DEEPSEEK_API_KEY and DATABASE_URL):
    python scripts/extract_claims_batch.py --limit-chunks 50
    python scripts/extract_claims_batch.py --document-id <uuid>
    python scripts/extract_claims_batch.py --limit-chunks 5 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from typing import Any

from research_shared.claims import claims_near_duplicate, normalise_claim
from research_shared.db import DatabaseConfig, DatabasePool

CONTENT_TYPE_CLAIM = "claim"
EXTRACTOR = "crew.extract_claims@v1"

_WS = re.compile(r"\s+")


def normalise(claim_text: str) -> str:
    return _WS.sub(" ", claim_text.strip().lower())


def claim_hash(claim_text: str) -> str:
    return hashlib.sha256(normalise(claim_text).encode("utf-8")).hexdigest()[:24]


class NearDupIndex:
    """In-memory token index so near-duplicate detection stays linear per claim."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.texts: dict[str, str] = {}
        self.by_token: dict[str, set[str]] = {}
        for row in rows:
            self.add(str(row["id"]), row["body"] or "")

    def add(self, claim_id: str, text: str) -> None:
        self.texts[claim_id] = text
        for token in set(normalise_claim(text).split()):
            self.by_token.setdefault(token, set()).add(claim_id)

    def find(self, text: str) -> str | None:
        tokens = set(normalise_claim(text).split())
        candidates: set[str] = set()
        for token in tokens:
            candidates |= self.by_token.get(token, set())
        # Compare against the most overlapping candidates first; cap the work so a
        # common word cannot make one claim scan the whole corpus.
        ranked = sorted(candidates, key=lambda cid: len(tokens & set(normalise_claim(self.texts[cid]).split())), reverse=True)
        for cid in ranked[:50]:
            if claims_near_duplicate(text, self.texts[cid]):
                return cid
        return None


async def load_near_dup_index(db: Any) -> NearDupIndex:
    rows = await db.fetch(
        "SELECT id, body FROM knowledge_graph_nodes WHERE content_type = 'claim'"
    )
    return NearDupIndex([dict(r) for r in rows])


async def register_claim_type(db: Any) -> None:
    await db.execute(
        "INSERT INTO content_type_registry "
        "(name, description, required_params, optional_params, voice_profile) "
        "VALUES ($1, $2, '[]'::jsonb, '[]'::jsonb, NULL) "
        "ON CONFLICT (name) DO NOTHING",
        CONTENT_TYPE_CLAIM,
        "A falsifiable claim extracted from a fulltext chunk, with provenance.",
    )


CHUNK_SQL = """
SELECT c.id                              AS chunk_id,
       c.body                            AS body,
       c.unit_id                         AS unit_id,
       c.collection                      AS collection,
       d.id                              AS document_id,
       d.title                           AS document_title,
       (c.metadata->>'chunk_index')::int AS chunk_index
FROM knowledge_graph_nodes c
JOIN knowledge_graph_nodes d ON d.id = c.unit_id
WHERE c.content_type = 'fulltext_chunk'
  AND d.content_type = 'fulltext_document'
  AND ($1::text IS NULL OR c.collection = $1)
  AND ($2::uuid IS NULL OR c.unit_id = $2)
  AND NOT EXISTS (
      SELECT 1 FROM knowledge_graph_nodes k
      WHERE k.content_type = 'claim' AND k.metadata->>'source_chunk_id' = c.id::text
  )
  -- A chunk that was attempted and yielded nothing is settled, not pending.
  -- Without this the sweep re-pays the LLM for the same empty chunk every run.
  AND coalesce(c.metadata->>'claim_extraction', '') <> 'empty'
ORDER BY d.title, (c.metadata->>'chunk_index')::int
LIMIT $3
"""


async def store_claim(
    db: Any,
    claim: dict,
    chunk: dict,
    dry_run: bool,
    index: NearDupIndex | None = None,
) -> str | None:
    """Insert one claim node + edge. Returns 'new', 'dupe' or None on failure."""
    text = (claim.get("claim_text") or "").strip()
    if not text:
        return None
    chash = claim_hash(text)

    existing = await db.fetchval(
        "SELECT id FROM knowledge_graph_nodes "
        "WHERE content_type = $1 AND metadata->>'claim_hash' = $2 LIMIT 1",
        CONTENT_TYPE_CLAIM,
        chash,
    )
    if existing:
        return "dupe"

    near_id = index.find(text) if index is not None else None
    if near_id:
        if not dry_run:
            # Keep the new occurrence: the surviving claim gains provenance from
            # this chunk instead of a second near-identical node.
            await db.execute(
                "INSERT INTO knowledge_graph_edges "
                "(source_id, target_id, relation_type, weight, metadata) "
                "VALUES ($1, $2, 'derived_from', $3, $4) "
                "ON CONFLICT (source_id, target_id, relation_type) DO NOTHING",
                near_id,
                str(chunk["chunk_id"]),
                float(claim.get("confidence_0_1") or 0.5),
                json.dumps({"extractor": EXTRACTOR, "occurrence": True}),
            )
        return "dupe"
    if dry_run:
        return "new"

    claim_id = str(uuid.uuid4())
    metadata = {
        "claim_hash": chash,
        "source_document_id": str(chunk["document_id"]),
        "source_document_title": chunk["document_title"],
        "source_chunk_id": str(chunk["chunk_id"]),
        "chunk_index": chunk["chunk_index"],
        "topic": claim.get("topic") or "",
        "confidence": claim.get("confidence_0_1"),
        "rationale": claim.get("rationale") or "",
        "score": claim.get("score"),
        "reasons": claim.get("reasons") or [],
        "extractor": EXTRACTOR,
    }
    await db.execute(
        "INSERT INTO knowledge_graph_nodes "
        "(id, title, content_type, body, metadata, collection, unit_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        claim_id,
        text[:120],
        CONTENT_TYPE_CLAIM,
        text,
        json.dumps(metadata),
        chunk["collection"] or "research",
        chunk["unit_id"],
    )
    await db.execute(
        "INSERT INTO knowledge_graph_edges "
        "(source_id, target_id, relation_type, weight, metadata) "
        "VALUES ($1, $2, 'derived_from', $3, $4) "
        "ON CONFLICT (source_id, target_id, relation_type) DO NOTHING",
        claim_id,
        str(chunk["chunk_id"]),
        float(claim.get("confidence_0_1") or 0.5),
        json.dumps({"extractor": EXTRACTOR}),
    )
    if index is not None:
        index.add(claim_id, text)
    return "new"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="research")
    ap.add_argument("--document-id", default=None)
    ap.add_argument("--limit-chunks", type=int, default=50)
    ap.add_argument("--max-claims", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=4, help="parallel LLM calls")
    ap.add_argument("--wave", type=int, default=24, help="chunks per stored batch")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    from saimon_mcp.crew.claim_extract import run_extract_claims

    db = DatabasePool(DatabaseConfig(database_url=db_url))
    await register_claim_type(db)

    index = await load_near_dup_index(db)
    print(f"{len(index.texts)} existing claim(s) indexed", flush=True)

    chunks = await db.fetch(
        CHUNK_SQL,
        args.collection,
        args.document_id,
        args.limit_chunks,
    )
    print(f"{len(chunks)} chunk(s) to process", flush=True)

    counts = {"new": 0, "dupe": 0, "empty": 0, "chunk_fail": 0}
    sem = asyncio.Semaphore(max(1, args.concurrency))
    done = 0

    def _extract_sync(text: str) -> list[dict]:
        # run_extract_claims is async but its LLM call is blocking, so give each
        # call its own loop in a worker thread instead of serialising the run.
        return asyncio.run(run_extract_claims(text, max_claims=args.max_claims))

    async def process(chunk: dict) -> tuple[dict, list[dict] | None]:
        async with sem:
            try:
                return chunk, await asyncio.to_thread(_extract_sync, chunk["body"])
            except Exception:  # noqa: BLE001 — one bad chunk must not stop the run
                return chunk, None

    # Store in waves: a whole-corpus gather would hold every result in memory and
    # write nothing until the last chunk finished, losing progress on a restart.
    wave = max(1, args.wave)
    for offset in range(0, len(chunks), wave):
        batch = chunks[offset : offset + wave]
        for chunk, claims in await asyncio.gather(*(process(c) for c in batch)):
            done += 1
            label = f"[{done}/{len(chunks)}]"
            if claims is None:
                counts["chunk_fail"] += 1
                print(f"{label} ERROR could not extract", flush=True)
                continue
            if not claims:
                counts["empty"] += 1
                if not args.dry_run:
                    await db.execute(
                        "UPDATE knowledge_graph_nodes "
                        "SET metadata = metadata || '{\"claim_extraction\": \"empty\"}'::jsonb "
                        "WHERE id = $1",
                        chunk["chunk_id"],
                    )
                print(
                    f"{label} none  {chunk['document_title'][:50]} #{chunk['chunk_index']}",
                    flush=True,
                )
                continue
            stored = 0
            for claim in claims:
                outcome = await store_claim(db, claim, chunk, args.dry_run, index)
                if outcome == "new":
                    counts["new"] += 1
                    stored += 1
                elif outcome == "dupe":
                    counts["dupe"] += 1
            print(
                f"{label} +{stored:2d}/{len(claims):2d} "
                f"{chunk['document_title'][:48]} #{chunk['chunk_index']}",
                flush=True,
            )

    print(
        f"\nclaims new={counts['new']} dupe={counts['dupe']} "
        f"chunks_without_claims={counts['empty']} chunk_errors={counts['chunk_fail']}"
        + (" (dry run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
