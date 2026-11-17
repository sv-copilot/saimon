#!/usr/bin/env python3
"""Bulk-ingest local document trees, and backfill their embeddings.

Direct database path for volume work: the API's ``store_content`` costs a
request, a log line and a model call per chunk, which is right for one document
and wrong for six thousand. This walks the same source manifest, chunks the same
way, and writes in batches of 500.

Idempotent by ``metadata.sha256``. ``--embed`` fills NULL embeddings in place,
highest-value collections first, and is resumable: a second run picks up whatever
is still NULL.

    python scripts/bulk_ingest.py --write --host
    python scripts/bulk_ingest.py --embed --batch 32 --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from ingest_sources import (
    MIN_CHARS,
    SOURCES,
    chunk_text,
    classify,
    iter_files,
    resolve_root,
    title_for,
)

BATCH = 500
EMBED_PRIORITY = ["site_content", "drake_pmo", "drake_public", "kdp", "saimon_self",
                  "novel_canon", "writing", "governance", "vault"]


async def _flush(conn, pending: list[tuple], totals: dict) -> None:
    if not pending:
        return
    await conn.executemany(
        "INSERT INTO knowledge_graph_nodes "
        "(title, content_type, body, metadata, collection) "
        "VALUES ($1, 'source_document', $2, $3::jsonb, $4)", pending)
    totals["stored"] += len(pending)
    pending.clear()


async def write(args) -> int:
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO content_type_registry (name, description, required_params, optional_params) "
            "VALUES ('source_document', 'A chunk of a local document ingested into the graph.', "
            "'[]'::jsonb, '[]'::jsonb) ON CONFLICT (name) DO NOTHING"
        )
        known = {r["h"] for r in await conn.fetch(
            "SELECT metadata->>'sha256' AS h FROM knowledge_graph_nodes WHERE metadata ? 'sha256'")}
        print(f"existing chunk hashes: {len(known)}", flush=True)

        stats: dict[str, dict] = {}
        started = time.time()
        for source in SOURCES:
            if args.only and source.name not in args.only:
                continue
            files = iter_files(source, args.host)
            if args.limit:
                files = files[: args.limit]
            totals = {"documents": len(files), "chunks": 0, "stored": 0, "skipped": 0}
            stats[source.name] = totals
            pending: list[tuple] = []

            for path in files:
                rel = str(path.relative_to(resolve_root(source, args.host)))
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    totals.setdefault("unreadable", 0)
                    totals["unreadable"] += 1
                    print(f"   unreadable: {rel} ({exc.strerror})", flush=True)
                    continue
                if len(text.strip()) < MIN_CHARS:
                    continue
                doc_type = classify(f"/{rel}", source.default_type)
                chunks = chunk_text(text)
                title = title_for(path, text)
                totals["chunks"] += len(chunks)
                for index, chunk in enumerate(chunks):
                    digest = hashlib.sha256(chunk.encode()).hexdigest()
                    if digest in known:
                        totals["skipped"] += 1
                        continue
                    known.add(digest)
                    meta = {
                        "sha256": digest, "source": source.name, "doc_type": doc_type,
                        "path": f"{source.host_root}/{rel}", "chunk_index": index,
                        "doc_chunks": len(chunks), "mtime": int(path.stat().st_mtime),
                    }
                    label = title if len(chunks) == 1 else f"{title} [{index + 1}/{len(chunks)}]"
                    pending.append((label[:200], chunk, json.dumps(meta), source.collection))
                    if len(pending) >= BATCH:
                        await _flush(conn, pending, totals)
                if args.limit and totals["chunks"] and len(pending) >= BATCH:
                    await _flush(conn, pending, totals)
            await _flush(conn, pending, totals)
            print(f"-- {source.name}: {totals}", flush=True)
        print(json.dumps({"elapsed_s": round(time.time() - started, 1), "sources": stats}, indent=1))
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps({"elapsed_s": round(time.time() - started, 1),
                                                     "sources": stats}, indent=1))
    finally:
        await conn.close()
    return 0


async def embed(args) -> int:
    import asyncpg

    from research_shared.embedding import embed_local

    model_path = os.environ.get("SAIMON_EMBEDDING_MODEL_PATH", "")
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    total = 0
    started = time.time()
    try:
        order = args.only or EMBED_PRIORITY
        for collection in order:
            while True:
                rows = await conn.fetch(
                    "SELECT id, body FROM knowledge_graph_nodes "
                    "WHERE embedding IS NULL AND collection = $1 "
                    "AND ($3 = 1 OR abs(hashtext(id::text)) % $3 = $4) "
                    "ORDER BY created_at LIMIT $2",
                    collection, args.batch, args.shards, args.shard)
                if not rows:
                    break
                for row in rows:
                    vector = embed_local(row["body"], model_path=model_path or None)
                    if vector is None:
                        continue
                    await conn.execute(
                        "UPDATE knowledge_graph_nodes SET embedding = $1::vector WHERE id = $2",
                        json.dumps(vector), row["id"])
                    total += 1
                elapsed = time.time() - started
                rate = total / elapsed if elapsed else 0
                print(f"   embedded {total} ({collection}), {rate:.2f}/s", flush=True)
                if args.limit and total >= args.limit:
                    print("limit reached")
                    return 0
                if args.batch and total % 400 == 0:
                    pass
    finally:
        await conn.close()
    print(json.dumps({"embedded": total, "elapsed_s": round(time.time() - started, 1)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--only", action="append")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--host", action="store_true")
    ap.add_argument("--report", default="")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    args = ap.parse_args()
    if args.write:
        return asyncio.run(write(args))
    if args.embed:
        return asyncio.run(embed(args))
    ap.error("choose --write or --embed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
