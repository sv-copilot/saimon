#!/usr/bin/env python3
"""Baseline: plain keyword search over the same files.

Not a straw man — this is what a folder of markdown plus ripgrep gives you. Every
file is loaded once, scored by how many of the query's content words it contains,
and the top eight are treated as the retrieved context. Same tasks, same scoring
as `measure_retrieval.py`, so the two numbers are comparable.

    python scripts/baseline_grep.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from eval_harness.ab import load_tasks  # noqa: E402
from research_shared.rerank import content_tokens  # noqa: E402

SOURCES = [
    "drake-governance/.docs", "drake-public", "drake-pmo",
    "spencervaradi-site/src/content", "spencervaradi-site/src/pages",
    "spencervaradi-site/src/data", "vaults/workspace", "writing",
    "work/needle", "work/hand-recovery", "reference", "saimon/docs",
]
SUFFIXES = {".md", ".markdown", ".mdx", ".txt", ".json", ".yaml", ".yml", ".astro", ".ts"}
SKIP = {".git", "node_modules", "audio", "piper-venv", "__pycache__"}


def passage(text: str, terms: set[str], width: int = 1400) -> str:
    """The window around the first matching term — same budget as one chunk.

    A whole file is not a fair comparison: eight files is roughly 100 KB of
    context against Saimon's 11 K. The window keeps the two tools at the same
    size so the difference measured is retrieval quality, not context volume.
    """
    lowered = text.lower()
    position = min((lowered.find(term) for term in terms if lowered.find(term) != -1), default=0)
    start = max(0, position - width // 4)
    return text[start : start + width]


def load_corpus(home: Path) -> list[tuple[str, set[str], str, str]]:
    corpus: list[tuple[str, set[str], str, str]] = []
    for source in SOURCES:
        root = home / source
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            if any(part in SKIP or part.startswith(".") for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) < 120:
                continue
            corpus.append((str(path.relative_to(home)), set(content_tokens(text)),
                           text.lower(), text))
    return corpus


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/tasks-v3.json"))
    parser.add_argument("--home", default="/home/hermes")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    corpus = load_corpus(Path(args.home))
    print(f"files: {len(corpus)}", file=sys.stderr)

    tasks = [t for t in load_tasks(args.tasks) if t["kind"] == "answerable"]
    grounded = recalled = gold_tasks = 0
    reciprocal = 0.0
    misses = []
    for task in tasks:
        terms = content_tokens(task["query"])
        scored = sorted(
            corpus,
            key=lambda item: (-len(terms & item[1]), len(item[2])),
        )[: args.k]
        blob = " ".join(passage(item[3], terms) for item in scored).lower()
        missing = [f for f in task.get("must_include", []) if f.lower() not in blob]
        grounded += int(not missing)
        rank = 0
        if task.get("gold"):
            gold_tasks += 1
            needle = task["gold"].lower().replace("-", " ")
            for index, (path, _, _, _) in enumerate(scored, 1):
                if needle in path.lower().replace("-", " ").replace("_", " "):
                    rank = index
                    break
            recalled += int(rank > 0)
            reciprocal += (1.0 / rank) if rank else 0.0
        if missing or (task.get("gold") and rank == 0):
            misses.append({"id": task["id"], "missing": missing, "gold_rank": rank})

    summary = {
        "baseline": "keyword over files",
        "k": args.k,
        "files": len(corpus),
        "answerable": len(tasks),
        "grounding_at_k": round(grounded / len(tasks), 4) if tasks else 0.0,
        "recall_at_k": round(recalled / gold_tasks, 4) if gold_tasks else None,
        "mrr": round(reciprocal / gold_tasks, 4) if gold_tasks else None,
        "misses": misses[:20],
    }
    print(json.dumps(summary, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
