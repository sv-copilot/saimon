#!/usr/bin/env python3
"""Rebuild the corpus with the current chunker and embedding path (#260).

Documents were ingested with a fixed-window chunker (92.5% of chunks ended
mid-sentence) and, unless the prefix flag is on, without nomic task prefixes.
This re-ingests every research document through the live API, which re-chunks,
re-embeds and replaces that document's chunks atomically per document.

Claims are extracted from chunks, so a rebuilt document leaves its old claims
pointing at deleted chunks. `--drop-claims` removes them first; re-extraction is
`scripts/extract_claims_batch.py`, run afterwards.

Safety: refuses to start without a recent backup manifest, and reports counts
before/after so the change is measured rather than assumed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_golden import _api_key, _post  # noqa: E402

PSQL = ["sg", "docker", "-c", "docker exec -i saimon-postgres psql -U saimon -d saimon -At"]


def psql(sql: str) -> list[list[str]]:
    result = subprocess.run(
        ["sg", "docker", "-c", "docker exec -i saimon-postgres psql -U saimon -d saimon -At"],
        input=sql, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    return [line.split("|") for line in result.stdout.strip().splitlines() if line]


def counts() -> dict[str, int]:
    rows = psql(
        "select count(*) filter (where content_type='fulltext_document'),"
        " count(*) filter (where content_type='fulltext_chunk'),"
        " count(*) filter (where content_type='fulltext_chunk' and embedding is null),"
        " count(*) filter (where content_type='claim')"
        " from knowledge_graph_nodes;"
    )
    docs, chunks, nulls, claims = (int(x) for x in rows[0])
    return {"documents": docs, "chunks": chunks, "chunks_without_embedding": nulls, "claims": claims}


def mid_sentence_rate() -> float:
    rows = psql(
        "select round(100.0*sum(case when right(body,1) in ('.','!','?') then 0 else 1 end)/count(*),1)"
        " from knowledge_graph_nodes where content_type='fulltext_chunk';"
    )
    return float(rows[0][0] or 0)


def documents(limit: int | None) -> list[tuple[str, str]]:
    sql = (
        "select metadata->>'doi', title from knowledge_graph_nodes"
        " where content_type='fulltext_document'"
        "   and coalesce(metadata->>'status','ready') <> 'failed'"
        "   and metadata->>'doi' like 'url:%'"
        " order by created_at"
    )
    if limit:
        sql += f" limit {int(limit)}"
    return [(row[0], row[1]) for row in psql(sql + ";")]


def require_backup(dump: str) -> None:
    """A verified dump is the precondition; a stale one is not good enough."""
    path = Path(dump)
    if not path.is_file():
        raise SystemExit(f"no dump at {dump} — run scripts/saimon-backup.sh first")
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > 2:
        raise SystemExit(f"dump is {age_hours:.1f}h old — take a fresh backup first")
    if path.stat().st_size < 1_000_000:
        raise SystemExit(f"dump looks truncated ({path.stat().st_size} bytes)")


def drop_claims(doi: str) -> int:
    rows = psql(
        "with doomed as (select id from knowledge_graph_nodes "
        " where content_type='claim' and metadata->>'source_document_id' in "
        " (select id::text from knowledge_graph_nodes where content_type='fulltext_document'"
        "  and metadata->>'doi' = " + sql_literal(doi) + ")) "
        "select count(*) from doomed;"
    )
    psql(
        "delete from knowledge_graph_edges where source_id in "
        "(select id from knowledge_graph_nodes where content_type='claim' "
        " and metadata->>'source_document_id' in "
        " (select id::text from knowledge_graph_nodes where content_type='fulltext_document'"
        "  and metadata->>'doi' = " + sql_literal(doi) + "));"
    )
    psql(
        "delete from knowledge_graph_nodes where content_type='claim' and metadata->>'source_document_id' in "
        "(select id::text from knowledge_graph_nodes where content_type='fulltext_document'"
        "  and metadata->>'doi' = " + sql_literal(doi) + ");"
    )
    return int(rows[0][0] or 0)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-url", default="http://127.0.0.1:8101")
    ap.add_argument("--dump", required=True, help="path to the fresh .sql.gz dump")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--drop-claims", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="required: this rewrites production rows")
    args = ap.parse_args()

    if not args.confirm:
        print("refusing to run without --confirm (rewrites chunk rows in production)", file=sys.stderr)
        return 2
    require_backup(args.dump)

    key = _api_key("SAIMON_SEARCH_KEY")
    if not key:
        print("SAIMON_SEARCH_KEY is not set", file=sys.stderr)
        return 2

    before = counts()
    before_mid = mid_sentence_rate()
    print(f"before: {before} mid_sentence={before_mid}%", flush=True)

    docs = documents(args.limit)
    print(f"{len(docs)} document(s) to rebuild", flush=True)

    failed: list[tuple[str, str]] = []
    t0 = time.time()
    for index, (doi, title) in enumerate(docs, 1):
        url = doi.split("url:", 1)[1]
        if args.drop_claims:
            removed = drop_claims(doi)
            if removed:
                print(f"  dropped {removed} stale claim(s) for {title[:40]}", flush=True)
        _, payload = _post(args.search_url, key, "ingest_document",
                           {"url": url, "title": title, "collection": "research"}, timeout=900)
        ok = payload.get("status") == "success"
        chunks = (payload.get("data") or {}).get("chunk_count")
        print(f"[{index}/{len(docs)}] {'ok  ' if ok else 'FAIL'} {int(time.time() - t0)}s chunks={chunks} {title[:50]}",
              flush=True)
        if not ok:
            failed.append((title, str(payload.get("errors"))[:120]))

    after = counts()
    after_mid = mid_sentence_rate()
    print(json.dumps({
        "before": before, "after": after, "failed": failed,
        "mid_sentence_before": before_mid, "mid_sentence_after": after_mid,
        "elapsed_s": int(time.time() - t0),
    }, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
