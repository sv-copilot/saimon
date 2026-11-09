#!/usr/bin/env python3
"""Corpus-perturbation stability check (SAIMON-RETRIEVAL-STABILITY-1).

Retrieval scores are relative: adding documents changes the candidate set, which
moved `pgvector hnsw tuning` from 0.816 to a sub-threshold score on 2026-11-08.
Nothing in the suite caught it, because every other check runs against a fixed
corpus.

This script measures the probe set, perturbs the corpus with N real documents,
measures again, and fails when a probe's verdict changes. The perturbation
documents are marked `failed` afterwards, which the retrieval path already
excludes, so the corpus is left as it was.

Run before a release, against a live stack:

    python scripts/retrieval_stability.py --perturb 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_golden import _api_key, _post, measure_retrieval

SUITE = ROOT / "fixtures" / "golden" / "suite.json"

# Public, lawfully readable documents used only as corpus noise.
PERTURBATION_DOCS = [
    ("Wikipedia: Bicycle", "https://en.wikipedia.org/wiki/Bicycle"),
    ("Wikipedia: Sourdough", "https://en.wikipedia.org/wiki/Sourdough"),
    ("Wikipedia: Tide", "https://en.wikipedia.org/wiki/Tide"),
    ("Wikipedia: Latitude", "https://en.wikipedia.org/wiki/Latitude"),
]


def verdicts(rows: list[dict]) -> dict[str, str]:
    """Reduce measurement rows to a comparable verdict per case."""
    out: dict[str, str] = {}
    for row in rows:
        if row.get("kind") == "abstain":
            out[row["id"]] = "abstain" if row.get("ok") else "leak"
        else:
            out[row["id"]] = "hit" if row.get("hit") else "miss"
    return out


def compare_verdicts(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    """Any changed verdict is a flip — including hit -> miss and miss -> leak."""
    flips = []
    for case_id in sorted(set(before) | set(after)):
        b, a = before.get(case_id), after.get(case_id)
        if b != a:
            flips.append({"id": case_id, "before": b, "after": a})
    return flips


def ingest(url: str, title: str, key: str, base: str) -> bool:
    _, payload = _post(
        base, key, "ingest_document",
        {"url": url, "title": title, "collection": "perturbation"}, timeout=600,
    )
    return payload.get("status") == "success"


def retire(url: str) -> bool:
    """Mark the perturbation document failed so retrieval ignores it again.

    Uses the same metadata contract as the lifecycle module; runs through the
    postgres container because this is a host-side operator tool.
    """
    import subprocess

    sql = (
        "UPDATE knowledge_graph_nodes "
        "SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('status','failed'), "
        "    updated_at = now() "
        "WHERE content_type = 'fulltext_document' AND metadata->>'doi' = $doi$" + "url:" + url + "$doi$;"
    )
    result = subprocess.run(
        ["sg", "docker", "-c", "docker exec -i saimon-postgres psql -U saimon -d saimon"],
        input=sql, text=True, capture_output=True, check=False,
    )
    return result.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-url", default="http://127.0.0.1:8101")
    ap.add_argument("--perturb", type=int, default=3)
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    key = _api_key("SAIMON_SEARCH_KEY")
    if not key:
        print("SAIMON_SEARCH_KEY is not set", file=sys.stderr)
        return 2

    suite = json.loads(SUITE.read_text())
    cases = suite["cases"]["retrieval"]

    _, before_rows = measure_retrieval(cases, args.search_url, key, limit=args.limit)
    before = verdicts(before_rows)
    print(f"before: {before}", flush=True)

    ingested = []
    for title, url in PERTURBATION_DOCS[: args.perturb]:
        ok = ingest(url, title, key, args.search_url)
        print(f"  perturb {'ok ' if ok else 'FAIL'} {title}", flush=True)
        if ok:
            ingested.append((title, url))

    try:
        _, after_rows = measure_retrieval(cases, args.search_url, key, limit=args.limit)
        after = verdicts(after_rows)
        flips = compare_verdicts(before, after)
        print(f"after:  {after}", flush=True)
        print(json.dumps({"perturbed": len(ingested), "flips": flips}, indent=2))
    finally:
        for title, url in ingested:
            if not retire(url):
                print(f"  WARNING: could not retire {title}; remove it manually")
        print(f"retired {len(ingested)} perturbation document(s)")

    return 0 if not flips else 1


if __name__ == "__main__":
    raise SystemExit(main())
