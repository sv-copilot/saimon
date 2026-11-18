#!/usr/bin/env python3
"""Measure retrieval quality without a model in the loop.

Groundedness — do the retrieved passages contain the facts the task requires —
is a property of retrieval alone. The A/B's success rate carries generation
sampling noise (the model-alone baseline moved eight points between two
identical runs); this does not. One search call per task, no completions.

    python scripts/measure_groundedness.py --url http://127.0.0.1:8101 --k 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from eval_harness.ab import load_tasks


def search(url: str, query: str, limit: int, key: str) -> dict:
    body = json.dumps({"trace_id": str(uuid.uuid4()), "content_type": "probe",
                       "parameters": {"query": query, "limit": limit}}).encode()
    request = urllib.request.Request(
        url.rstrip("/") + "/tools/search_knowledge_graph", data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return (json.loads(response.read()) or {}).get("data") or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8101")
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/tasks-v2.json"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--key-env", default="SAIMON_SEARCH_KEY")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    key = os.environ.get(args.key_env, "").split(",")[0].strip()
    if not key:
        print(f"{args.key_env} not set", file=sys.stderr)
        return 2

    tasks = [t for t in load_tasks(args.tasks) if t["kind"] == "answerable"]
    per_collection: dict[str, list[int]] = {}
    misses: list[dict] = []
    grounded = 0
    latencies: list[float] = []

    for task in tasks:
        started = time.perf_counter()
        data = search(args.url, task["query"], args.k, key)
        latencies.append((time.perf_counter() - started) * 1000)
        passages = " ".join((r.get("body") or "") + " " + (r.get("title") or "")
                            for r in data.get("results") or []).lower()
        missing = [fact for fact in task.get("must_include", []) if fact.lower() not in passages]
        ok = not missing and not data.get("no_strong_evidence")
        grounded += int(ok)
        bucket = task.get("collection", "other")
        per_collection.setdefault(bucket, []).append(int(ok))
        if not ok:
            misses.append({"id": task["id"], "collection": bucket, "missing": missing,
                           "hits": len(data.get("results") or []),
                           "abstain": data.get("abstain_reason")})

    summary = {
        "tasks": len(tasks),
        "grounded": grounded,
        "groundedness": round(grounded / len(tasks), 4) if tasks else 0.0,
        "k": args.k,
        "latency_p50_ms": round(sorted(latencies)[len(latencies) // 2], 1) if latencies else 0,
        "latency_p95_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1) if latencies else 0,
        "by_collection": {c: {"n": len(v), "grounded": sum(v), "rate": round(sum(v) / len(v), 3)}
                          for c, v in sorted(per_collection.items())},
        "misses": misses,
    }
    print(json.dumps(summary, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
