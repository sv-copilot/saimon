#!/usr/bin/env python3
"""Adversarial retrieval: does the system know when a question is wrong?

Three outcomes per question, in descending order of quality:

  corrected  something was returned and it contains the fact that exposes the
             premise ("eleven states", not twelve)
  silent     nothing was returned, so the question cannot be answered from the
             corpus and the generator has nothing to hallucinate from
  fooled     something was returned that shares the question's vocabulary and
             does not correct it. This is the case that produces a confident
             wrong answer downstream.

    python scripts/measure_adversarial.py --k 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/adversarial.json"))
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--key-env", default="SAIMON_SEARCH_KEY")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    key = os.environ.get(args.key_env, "").split(",")[0].strip()
    if not key:
        print(f"{args.key_env} not set", file=sys.stderr)
        return 2

    tasks = json.loads(Path(args.tasks).read_text())["tasks"]
    corrected = silent = fooled = 0
    rows = []
    for task in tasks:
        data = search(args.url, task["query"], args.k, key)
        results = data.get("results") or []
        blob = " ".join((r.get("body") or "") + " " + (r.get("title") or "")
                        for r in results).lower()
        # The retrieval layer counts as having caught the premise when it either
        # returns the fact that contradicts the question, or flags the conflict
        # outright ("the corpus says eleven, you said twelve").
        conflict = bool(data.get("premise_conflict"))
        has_correction = conflict or any(
            token.lower() in blob for token in task.get("correction", [])
        )
        if not results:
            outcome = "silent"
            silent += 1
        elif has_correction:
            outcome = "corrected"
            corrected += 1
        else:
            outcome = "fooled"
            fooled += 1
        rows.append({"id": task["id"], "outcome": outcome, "hits": len(results),
                     "conflict": conflict,
                     "numbers": data.get("conflicting_numbers") or [],
                     "top": (results[0].get("title") if results else None)})

    total = len(tasks)
    summary = {
        "tasks": total,
        "corrected": corrected,
        "silent": silent,
        "fooled": fooled,
        "fooled_rate": round(fooled / total, 4) if total else 0.0,
        "defended_rate": round((corrected + silent) / total, 4) if total else 0.0,
        "rows": rows,
    }
    print(json.dumps(summary, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
