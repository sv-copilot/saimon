#!/usr/bin/env python3
"""Retrieval KPIs, measured without a model in the loop.

Three separate questions, because they fail for different reasons:

- **recall@k** — did the document that answers the question come back at all?
  Needs a gold document on the task. Ranking can be wrong and still pass this.
- **grounding@k** — do the retrieved passages contain the facts the answer needs?
  Independent of ranking, and the metric the release gate already uses.
- **false-answer rate** — on questions the corpus cannot answer, how often does
  search return something anyway? Abstention is a product property, not a
  retrieval nicety: a confident wrong hit is worse than nothing.

All three are deterministic given the corpus, so a change of two points is a
change of two points. The A/B's answer success carries generation sampling noise
(the model-alone baseline moved eight points between identical runs).

    python scripts/measure_retrieval.py --k 8
    python scripts/measure_retrieval.py --k 8 --json-out reports/retrieval.json
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

from eval_harness.ab import load_tasks  # noqa: E402


def search(url: str, query: str, limit: int, key: str) -> dict:
    body = json.dumps({"trace_id": str(uuid.uuid4()), "content_type": "probe",
                       "parameters": {"query": query, "limit": limit}}).encode()
    request = urllib.request.Request(
        url.rstrip("/") + "/tools/search_knowledge_graph", data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return (json.loads(response.read()) or {}).get("data") or {}


def _normalise(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ")


def gold_rank(results: list[dict], gold: str) -> int:
    """1-based rank of the gold document, or 0 when it is absent."""
    needle = _normalise(gold)
    for index, row in enumerate(results, 1):
        haystack = _normalise(f"{row.get('title') or ''} {row.get('body') or ''}")
        if needle in haystack:
            return index
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8101")
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/tasks-v3.json"))
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--key-env", default="SAIMON_SEARCH_KEY")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    key = os.environ.get(args.key_env, "").split(",")[0].strip()
    if not key:
        print(f"{args.key_env} not set", file=sys.stderr)
        return 2

    tasks = load_tasks(args.tasks)
    answerable = [t for t in tasks if t["kind"] == "answerable"]
    unanswerable = [t for t in tasks if t["kind"] == "unanswerable"]

    latencies: list[float] = []
    grounded = recalled = gold_tasks = 0
    reciprocal_rank = 0.0
    by_collection: dict[str, dict[str, int]] = {}
    misses: list[dict] = []

    for task in answerable:
        started = time.perf_counter()
        data = search(args.url, task["query"], args.k, key)
        latencies.append((time.perf_counter() - started) * 1000)
        results = data.get("results") or []
        passages = " ".join((r.get("body") or "") + " " + (r.get("title") or "")
                            for r in results).lower()

        missing = [fact for fact in task.get("must_include", []) if fact.lower() not in passages]
        ok_ground = not missing and not data.get("no_strong_evidence")
        grounded += int(ok_ground)

        bucket = task.get("collection", "other")
        stats = by_collection.setdefault(bucket, {"n": 0, "grounded": 0, "recalled": 0})
        stats["n"] += 1
        stats["grounded"] += int(ok_ground)

        rank = 0
        if task.get("gold"):
            gold_tasks += 1
            rank = gold_rank(results, task["gold"])
            recalled += int(rank > 0)
            reciprocal_rank += (1.0 / rank) if rank else 0.0
            stats["recalled"] += int(rank > 0)

        if not ok_ground or (task.get("gold") and rank == 0):
            misses.append({"id": task["id"], "collection": bucket, "missing": missing,
                           "gold_rank": rank, "hits": len(results),
                           "abstain": data.get("abstain_reason")})

    false_answers = 0
    abstained = 0
    false_ids: list[str] = []
    for task in unanswerable:
        data = search(args.url, task["query"], args.k, key)
        results = data.get("results") or []
        if results:
            false_answers += 1
            false_ids.append(task["id"])
        else:
            abstained += 1

    summary = {
        "k": args.k,
        "tasks": {"answerable": len(answerable), "unanswerable": len(unanswerable)},
        "grounding_at_k": round(grounded / len(answerable), 4) if answerable else 0.0,
        "recall_at_k": round(recalled / gold_tasks, 4) if gold_tasks else None,
        "mrr": round(reciprocal_rank / gold_tasks, 4) if gold_tasks else None,
        "gold_tasks": gold_tasks,
        "abstention_rate": round(abstained / len(unanswerable), 4) if unanswerable else None,
        "false_answers": false_ids,
        "latency_p50_ms": round(sorted(latencies)[len(latencies) // 2], 1) if latencies else 0,
        "latency_p95_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1)
        if latencies else 0,
        "by_collection": {c: {**v, "grounding": round(v["grounded"] / v["n"], 3),
                              "recall": round(v["recalled"] / v["n"], 3)}
                          for c, v in sorted(by_collection.items())},
        "misses": misses,
    }
    print(json.dumps(summary, indent=1))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
