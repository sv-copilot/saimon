#!/usr/bin/env python3
"""Does putting the title in the embedded text help? Measure before re-ingesting.

Chunks are embedded from body alone, so a chunk titled "heroku-migration.md" whose
body opens mid-argument carries no title signal in its vector. Re-embedding 30k
chunks takes hours, so this compares the two texts on a fixed candidate pool in
memory first: same queries, same chunks, only the embedded text differs.

    python scripts/embed_title_experiment.py --pool 800
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research_shared.embedding import (  # noqa: E402
    DOCUMENT_PREFIX,
    EmbeddingConfig,
    embed_local,
    query_embed_text,
    task_prefixes_enabled,
)


def parse_vector(value) -> list[float]:
    """pgvector arrives as text unless the codec is registered for the connection."""
    if isinstance(value, str):
        return [float(part) for part in value.strip("[]").split(",") if part]
    return list(value)


def cosine(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    denominators = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
    denominators[denominators == 0] = 1.0
    return matrix @ query / denominators


async def main_async(args: argparse.Namespace) -> int:
    import asyncpg

    tasks = [t for t in json.loads(Path(args.tasks).read_text())["tasks"] if t.get("gold")]
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])

    golds = [t["gold"].lower() for t in tasks]
    rows = await conn.fetch(
        "SELECT id, title, body, embedding FROM knowledge_graph_nodes"
        " WHERE embedding IS NOT NULL ORDER BY random() LIMIT $1",
        args.pool,
    )
    for gold in golds:
        rows += await conn.fetch(
            "SELECT id, title, body, embedding FROM knowledge_graph_nodes"
            " WHERE embedding IS NOT NULL AND (title ILIKE $1 OR body ILIKE $1) LIMIT 4",
            f"%{gold}%",
        )
    await conn.close()

    unique = {row["id"]: row for row in rows}
    rows = list(unique.values())
    print(f"pool: {len(rows)} chunks, {len(tasks)} gold tasks", file=sys.stderr)

    config = EmbeddingConfig.from_env()
    prefix = DOCUMENT_PREFIX if task_prefixes_enabled() else ""

    old_matrix = np.array([parse_vector(row["embedding"]) for row in rows], dtype=np.float32)
    new_vectors = []
    for index, row in enumerate(rows):
        text = f"{prefix}{(row['title'] or '').strip()}\n\n{(row['body'] or '').strip()}"
        vector = embed_local(text, config.model, config.dimensions, config.model_path or None)
        if vector is None:
            print("embedding failed", file=sys.stderr)
            return 2
        new_vectors.append(vector)
        if (index + 1) % 100 == 0:
            print(f"  embedded {index + 1}/{len(rows)}", file=sys.stderr)
    new_matrix = np.array(new_vectors, dtype=np.float32)

    haystacks = [(row["title"] or "").lower() + " " + (row["body"] or "").lower() for row in rows]
    report = {"title": [], "body": []}
    for task in tasks:
        gold = task["gold"].lower()
        query = embed_local(query_embed_text(task["query"]), config.model,
                            config.dimensions, config.model_path or None)
        if query is None:
            continue
        query_vector = np.array(query, dtype=np.float32)
        for label, matrix in (("body", old_matrix), ("title", new_matrix)):
            ranking = np.argsort(-cosine(query_vector, matrix))
            rank = next(
                (position for position, index in enumerate(ranking, 1) if gold in haystacks[index]),
                0,
            )
            report[label].append(rank)

    def summarise(ranks: list[int]) -> dict:
        total = len(ranks) or 1
        return {
            "tasks": len(ranks),
            "recall@1": round(sum(1 for r in ranks if r == 1) / total, 3),
            "recall@5": round(sum(1 for r in ranks if 1 <= r <= 5) / total, 3),
            "recall@10": round(sum(1 for r in ranks if 1 <= r <= 10) / total, 3),
            "mrr": round(sum((1 / r) for r in ranks if r) / total, 3),
            "mean_rank": round(sum(r if r else len(rows) for r in ranks) / total, 1),
        }

    output = {label: summarise(ranks) for label, ranks in report.items()}
    output["pool"] = len(rows)
    output["ranks"] = report
    print(json.dumps({k: v for k, v in output.items() if k != "ranks"}, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(output, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/tasks-v3.json"))
    parser.add_argument("--pool", type=int, default=800)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
