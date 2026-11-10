#!/usr/bin/env python3
"""Verify every claim, resumably, from outside the containers.

Prior runs died when a deploy restarted the verify container mid-batch, and they
restarted from zero because nothing recorded progress. The ledger already records
every verdict, so the ledger *is* the checkpoint: this script selects only claims
whose text is not already in `verification_ledger`, and re-queries after each
pass. Killing it costs at most the in-flight requests.

    python3 scripts/verify_claims_resumable.py --limit 50
    python3 scripts/verify_claims_resumable.py            # until covered

Environment: DATABASE_URL (host-reachable) and SAIMON_VERIFY_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import asyncpg
import httpx

DEFAULT_VERIFY_URL = os.getenv("SAIMON_VERIFY_URL", "http://127.0.0.1:8105")
RATE_PER_MINUTE = float(os.getenv("SAIMON_VERIFY_RATE", "85"))
MAX_TEXT = 4000


def claim_text(row: asyncpg.Record) -> str:
    return f"{row['title'] or ''}. {row['body'] or ''}".strip()[:MAX_TEXT]


async def uncovered(conn: asyncpg.Connection, limit: int | None) -> list[asyncpg.Record]:
    """Claims whose text the ledger has no verdict for."""
    sql = """
        SELECT n.id, n.title, n.body
        FROM knowledge_graph_nodes n
        WHERE n.content_type = 'claim'
        ORDER BY n.created_at
    """
    rows = await conn.fetch(sql)
    seen = {r["claim_text"] for r in await conn.fetch("SELECT claim_text FROM verification_ledger")}
    pending = [r for r in rows if claim_text(r) not in seen]
    return pending[:limit] if limit else pending


async def coverage(conn: asyncpg.Connection) -> dict[str, float]:
    total = await conn.fetchval(
        "SELECT count(*) FROM knowledge_graph_nodes WHERE content_type = 'claim'"
    )
    ledger = await conn.fetchval(
        "SELECT count(DISTINCT claim_hash) FROM verification_ledger"
    )
    return {"claims": int(total), "verified": int(ledger),
            "percent": round(100.0 * ledger / total, 1) if total else 0.0}


async def verify_one(
    client: httpx.AsyncClient, key: str, row: asyncpg.Record, sem: asyncio.Semaphore
) -> str:
    text = claim_text(row)
    async with sem:
        for attempt in range(4):
            await asyncio.sleep(60.0 / RATE_PER_MINUTE)
            try:
                resp = await client.post(
                    f"{DEFAULT_VERIFY_URL}/tools/verify_claim",
                    json={
                        "trace_id": str(row["id"]),
                        "content_type": "probe",
                        "parameters": {"claim": text},
                    },
                    headers={"X-Saimon-API-Key": key},
                    timeout=90,
                )
            except httpx.HTTPError:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(2 ** attempt)
                continue
            data = (resp.json() or {}).get("data") or {}
            return str(data.get("overall_verdict") or "error")
        return "error"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--passes", type=int, default=1)
    args = ap.parse_args()

    key = os.getenv("SAIMON_VERIFY_KEY") or os.getenv("SAIMON_API_KEY") or ""
    dsn = os.getenv("DATABASE_URL") or ""
    if not key or not dsn:
        print("SAIMON_VERIFY_KEY and DATABASE_URL are required", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    sem = asyncio.Semaphore(args.workers)
    started = time.time()

    try:
        for pass_no in range(1, args.passes + 1):
            pending = await uncovered(conn, args.limit or None)
            print(f"pass {pass_no}: {len(pending)} claim(s) uncovered", flush=True)
            if not pending:
                break

            counts: dict[str, int] = {}
            done = 0

            async with httpx.AsyncClient() as client:
                async def one(row: asyncpg.Record) -> None:
                    nonlocal done
                    verdict = await verify_one(client, key, row, sem)
                    counts[verdict] = counts.get(verdict, 0) + 1
                    done += 1
                    if done % 200 == 0:
                        print(f"  {done}/{len(pending)} {counts}", flush=True)

                await asyncio.gather(*(one(r) for r in pending))

            print(f"pass {pass_no} verdicts: {counts}", flush=True)
            print(f"coverage: {json.dumps(await coverage(conn))}", flush=True)

        print(json.dumps({
            "coverage": await coverage(conn),
            "elapsed_s": round(time.time() - started, 1),
        }, indent=2))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
