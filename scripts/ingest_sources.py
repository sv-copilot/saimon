#!/usr/bin/env python3
"""Ingest local document trees into the knowledge graph.

Calls the product's own ``store_content`` tool once per chunk, so every node goes
through the same validation, universe resolution and audit path as any other
write. Nothing is inserted behind the API's back.

Idempotent by content hash: each chunk carries ``metadata.sha256`` and a chunk
that already exists is skipped, so a re-run after an edit stores only what
changed. Safe to interrupt and restart.

    python scripts/ingest_sources.py --dry-run
    python scripts/ingest_sources.py --only governance --limit 20
    python scripts/ingest_sources.py --report reports/ingest-2026-11-17.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
             ".mypy_cache", ".pytest_cache", ".obsidian", "audio", "piper-venv"}
SKIP_SUFFIX = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".m4a",
               ".zip", ".onnx", ".bin", ".woff", ".woff2", ".ttf", ".ico", ".mp4"}
MIN_CHARS = 120
TARGET_CHARS = 1400
OVERLAP_CHARS = 200


@dataclass(frozen=True)
class Source:
    name: str
    root: str            # mount point inside the container
    collection: str
    default_type: str
    host_root: str       # path a human would recognize in a citation
    exclude: tuple[str, ...] = ()


SOURCES = [
    Source("governance", "/src/governance", "governance", "strategy_doc",
           "drake-governance/.docs"),
    Source("drake", "/src/drake", "drake_public", "product_doc", "drake-public"),
    Source("drake_pmo", "/src/drake_pmo", "drake_pmo", "product_doc", "drake-pmo"),
    Source("site", "/src/site", "site_content", "page", "spencervaradi-site/src/content"),
    Source("writing", "/src/writing", "writing", "novel_chapter", "writing"),
    Source("needle", "/src/needle", "novel_canon", "novel_canon", "work/needle"),
    Source("kdp", "/src/kdp", "kdp", "kdp_listing", "work/hand-recovery"),
    Source("saimon_self", "/src/saimon", "saimon_self", "product_doc", "saimon"),
    Source("vault", "/src/vault", "vault", "vault_note", "vaults/workspace"),
]

TYPE_RULES = [
    ("/decision-log/", "decision_log"),
    ("/content/blog/", "blog_draft"),
    ("/offers/", "offer"),
    ("/planning/", "planning"),
    ("/blog/", "blog_post"),
    ("/case-studies/", "case_study"),
    ("/workshops/", "workshop"),
    ("/skills/", "skill"),
    ("/schemas/", "schema"),
    ("/books/", "novel_chapter"),
]


def classify(rel: str, default: str) -> str:
    for needle, content_type in TYPE_RULES:
        if needle in rel:
            return content_type
    return default


def chunk_text(text: str) -> list[str]:
    """Paragraph-aware chunks. Never splits a paragraph unless it is oversized."""
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= TARGET_CHARS:
        return [text] if text else []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= TARGET_CHARS:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
        while len(para) > TARGET_CHARS:
            chunks.append(para[:TARGET_CHARS])
            para = para[TARGET_CHARS - OVERLAP_CHARS:]
        current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c.strip()) >= 40]


def title_for(path: Path, text: str) -> str:
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:180]
    return path.stem.replace("-", " ").replace("_", " ")[:180]


def resolve_root(source: Source, host_mode: bool) -> Path:
    """Container mount path by default; the real home path with --host."""
    if host_mode:
        return Path("/home/hermes") / source.host_root
    return Path(source.root)


def iter_files(source: Source, host_mode: bool = False) -> list[Path]:
    root = resolve_root(source, host_mode)
    if not root.exists():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() in SKIP_SUFFIX:
                continue
            if p.suffix.lower() not in {".md", ".markdown", ".mdx", ".txt", ".json", ".yaml", ".yml"}:
                continue
            if any(x in str(p) for x in source.exclude):
                continue
            found.append(p)
    return sorted(found)


def ensure_content_type() -> None:
    """Register the ingest content type. The registry is an FK target, so a new
    content type must exist before any node can reference it."""
    import subprocess
    sql = ("INSERT INTO content_type_registry (name, description, required_params, optional_params) "
           "VALUES ('source_document', 'A chunk of a local document ingested into the graph.', "
           "'[]'::jsonb, '[]'::jsonb) ON CONFLICT (name) DO NOTHING")
    result = subprocess.run(
        ["docker", "exec", "-i", "saimon-postgres", "psql", "-U", "saimon", "-d", "saimon", "-At", "-c", sql],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"cannot register content type: {result.stderr.strip()[:200]}")


def existing_hashes(dsn_hint: str = "") -> set[str]:
    """Chunk hashes already in the graph, read over the local socket."""
    import subprocess
    sql = "select metadata->>'sha256' from knowledge_graph_nodes where metadata ? 'sha256'"
    result = subprocess.run(
        ["docker", "exec", "-i", "saimon-postgres", "psql", "-U", "saimon", "-d", "saimon", "-At", "-c", sql],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"cannot read existing hashes: {result.stderr.strip()[:200]}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def post(url: str, key: str, params: dict, timeout: int = 90) -> tuple[int, dict]:
    import uuid
    body = json.dumps({"trace_id": str(uuid.uuid4()), "content_type": "ingest",
                       "parameters": params}).encode()
    req = urllib.request.Request(
        f"{url}/tools/store_content", data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {"status": "error", "errors": [f"HTTP {exc.code}"]}
    except Exception as exc:  # noqa: BLE001 - network failures are per-chunk, not fatal
        return 0, {"status": "error", "errors": [str(exc)[:200]]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("SAIMON_GENERATE_URL", "http://127.0.0.1:8102"))
    ap.add_argument("--key-env", default="SAIMON_API_KEY")
    ap.add_argument("--only", action="append", help="source name(s) to ingest")
    ap.add_argument("--limit", type=int, default=0, help="stop after N documents (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--report", default="")
    ap.add_argument("--host", action="store_true", help="read $HOME paths instead of container mounts")
    args = ap.parse_args()

    raw = os.environ.get(args.key_env, "")
    # SAIMON_API_KEY is a comma-separated rotation list; the tool takes one key.
    key = next((k.strip() for k in raw.split(",") if k.strip()), "")
    if not args.dry_run and not key:
        print(f"missing {args.key_env} in environment", file=sys.stderr)
        return 2

    selected = [s for s in SOURCES if not args.only or s.name in args.only]
    if not args.dry_run:
        ensure_content_type()
    known = set() if args.dry_run else existing_hashes()
    print(f"existing chunk hashes: {len(known)}", flush=True)

    lock = threading.Lock()
    stats: dict[str, dict] = {}
    report_rows: list[dict] = []
    started = time.time()

    def ingest_doc(source: Source, path: Path) -> tuple[int, int, int, int]:
        rel = str(path.relative_to(resolve_root(source, args.host)))
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < MIN_CHARS:
            return 0, 0, 1, 0
        doc_type = classify(f"/{rel}", source.default_type)
        title = title_for(path, text)
        host_path = f"{source.host_root}/{rel}"
        chunks = chunk_text(text)
        stored = skipped = failed = 0
        for index, chunk in enumerate(chunks):
            digest = hashlib.sha256(chunk.encode()).hexdigest()
            with lock:
                if digest in known:
                    skipped += 1
                    continue
                known.add(digest)
            params = {
                "title": title if len(chunks) == 1 else f"{title} [{index + 1}/{len(chunks)}]",
                "content_type": "source_document",
                "body": chunk,
                "metadata": {
                    "sha256": digest, "source": source.name, "collection": source.collection,
                    "doc_type": doc_type, "title": title,
                    "path": host_path, "chunk_index": index, "doc_chunks": len(chunks),
                    "mtime": int(path.stat().st_mtime),
                },
            }
            status, payload = post(args.url, key, params)
            if status == 200 and payload.get("status") != "error":
                stored += 1
            else:
                failed += 1
                with lock:
                    report_rows.append({"path": host_path, "index": index,
                                        "error": (payload.get("errors") or ["unknown"])[0]})
                known.discard(digest)
        return len(chunks), stored, skipped, failed

    for source in selected:
        files = iter_files(source, args.host)
        if args.limit:
            files = files[: args.limit]
        totals = {"documents": len(files), "chunks": 0, "stored": 0, "skipped": 0, "failed": 0}
        stats[source.name] = totals
        if args.dry_run:
            sample = [str(p.relative_to(resolve_root(source, args.host))) for p in files[:3]]
            print(f"{source.name:12s} {len(files):5d} files  e.g. {sample}")
            continue
        print(f"-- {source.name}: {len(files)} documents", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(ingest_doc, source, p): p for p in files}
            for done, future in enumerate(as_completed(futures), 1):
                chunks, stored, skipped, failed = future.result()
                totals["chunks"] += chunks
                totals["stored"] += stored
                totals["skipped"] += skipped
                totals["failed"] += failed
                if done % 50 == 0:
                    print(f"   {done}/{len(files)} docs, stored {totals['stored']}, "
                          f"skipped {totals['skipped']}, failed {totals['failed']}", flush=True)
        print(f"   done: {totals}", flush=True)

    elapsed = round(time.time() - started, 1)
    summary = {"elapsed_s": elapsed, "sources": stats,
               "errors": report_rows[:200], "error_count": len(report_rows)}
    print(json.dumps(summary, indent=1)[:4000])
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(summary, indent=1))
        print(f"report: {args.report}")
    return 0 if not report_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
