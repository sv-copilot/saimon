#!/usr/bin/env python3
"""Prompt experiment: same retrieval, same model, two instructions.

The A/B says retrieval hands the facts to the model 69% of the time and the answer
still succeeds only 45% of the time. That gap is in the answer step, not the index,
so this compares two prompts against identical context — the shipped one, which
asks for three sentences, and one that demands exact figures and an explicit
refusal token.

    python scripts/prompt_experiment.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval_harness import ab  # noqa: E402

PROMPT_STRICT = (
    "Answer using only the passages below. Write the answer first, in one sentence.\n"
    "Quote names, numbers, identifiers and dates exactly as they appear in the passage — "
    "do not round, reformat or paraphrase them.\n"
    "Then give one sentence naming the passage that supports it.\n"
    "If no passage contains the answer, reply exactly: NOT_IN_CONTEXT\n\n"
    "Passages:\n{context}\n\nQuestion: {query}\nAnswer:"
)


PROMPT_EXTRACTIVE = (
    "Answer using only the passages below.\n"
    "Write one sentence that answers the question, using the passage's own words for "
    "names, numbers and technical terms.\n"
    "Then quote the single sentence from the passage that contains the answer, verbatim.\n"
    "If no passage answers it, reply exactly: NOT_IN_CONTEXT\n\n"
    "Passages:\n{context}\n\nQuestion: {query}\nAnswer:"
)


def normalise(text: str) -> str:
    """Compare facts, not typography: 1,500 and 1500 are the same number."""
    lowered = (text or "").lower()
    lowered = re.sub(r"(?<=\d),(?=\d)", "", lowered)
    return lowered


def score(answer: str, task: dict) -> dict:
    """The harness grader, with thousands separators ignored on both sides."""
    body = normalise(answer)
    refused = ab.is_refusal(answer) or "not_in_context" in body
    missing = [fact for fact in task.get("must_include", []) if normalise(fact) not in body]
    if task["kind"] == "unanswerable":
        return {"success": refused, "abstained": refused, "missing": []}
    return {"success": (not refused) and not missing, "abstained": refused, "missing": missing}


def search(url: str, query: str, limit: int, key: str) -> dict:
    body = json.dumps({
        "trace_id": str(uuid.uuid4()),
        "content_type": "probe",
        "parameters": {"query": query, "limit": limit},
    }).encode()
    request = urllib.request.Request(
        url.rstrip("/") + "/tools/search_knowledge_graph",
        data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return (json.loads(response.read()) or {}).get("data") or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=str(ROOT / "fixtures/ab/tasks-v3.json"))
    parser.add_argument("--url", default="http://127.0.0.1:8101")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--only", default="", help="restrict to ids matching this substring")
    parser.add_argument("--arms", default="both", choices=["both", "shipped"])
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    import os

    key = os.environ.get("SAIMON_SEARCH_KEY", "").split(",")[0].strip()
    if not key:
        print("SAIMON_SEARCH_KEY not set", file=sys.stderr)
        return 2

    from scripts.ab_eval import live_generate_factory  # noqa: PLC0415

    generate = live_generate_factory(args.model)
    tasks = ab.load_tasks(args.tasks)
    if args.only:
        tasks = [t for t in tasks if args.only in t["id"]]

    arms = {"shipped": ab.DEFAULT_PROMPT}
    if args.arms == "both":
        arms["extractive"] = PROMPT_EXTRACTIVE
    rows = []
    for task in tasks:
        payload = search(args.url, task["query"], args.limit, key)
        results = payload.get("results") or []
        context = "\n\n".join(
            f"[{index}] {row.get('title', '')}: {row.get('body', '')}".strip()
            for index, row in enumerate(results, 1)
        ) or ab.NO_CONTEXT
        grounded = ab.groundedness(context, task)
        entry = {"id": task["id"], "kind": task["kind"], "groundedness": grounded,
                 "retrieved": len(results)}
        for name, template in arms.items():
            answer = generate(ab.build_prompt(task["query"], context, template))
            entry[name] = {**score(answer, task), "answer": answer}
        rows.append(entry)
        marks = " ".join(
            f"{name}={'ok' if entry[name]['success'] else 'fail'}" for name in arms
        )
        print(f"{task['id']}: {marks}", file=sys.stderr)

    def summarise(name: str) -> dict:
        answerable = [r for r in rows if r["kind"] == "answerable"]
        unanswerable = [r for r in rows if r["kind"] == "unanswerable"]
        successes = sum(1 for r in answerable if r[name]["success"])
        refusals = sum(1 for r in unanswerable if r[name]["success"])
        return {
            "answerable": len(answerable),
            "answerable_success": round(successes / len(answerable), 4) if answerable else 0.0,
            "abstain_accuracy": round(refusals / len(unanswerable), 4) if unanswerable else None,
            "overall": round(
                (successes + refusals) / len(rows), 4
            ) if rows else 0.0,
        }

    grounded_values = [r["groundedness"] for r in rows if r["groundedness"] is not None]
    output = {
        "tasks": len(rows),
        "retrieval_groundedness": round(sum(grounded_values) / len(grounded_values), 4)
        if grounded_values else None,
        "shipped": summarise("shipped"),
        **({"extractive": summarise("extractive")} if "extractive" in arms else {}),
        "flips": [
            {
                "id": r["id"],
                **{name: r[name]["success"] for name in arms},
            }
            for r in rows
            if len({r[name]["success"] for name in arms}) > 1
        ],
    }
    print(json.dumps(output, indent=1))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({**output, "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
