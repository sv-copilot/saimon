#!/usr/bin/env python3
"""Measure four arms against the same tasks and grade a release against its goals.

    python scripts/ab_eval.py run  --provider live --current-url http://127.0.0.1:8101 \
        --previous-url http://127.0.0.1:8301 --out reports/ab/$(date +%F).json
    python scripts/ab_eval.py report --report reports/ab/2026-11-16.json
    python scripts/ab_eval.py gate   --report reports/ab/2026-11-16.json

Exit codes: run 0 measured; gate 0 pass, 1 fail, 2 nothing measured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval_harness import ab

DEFAULT_TASKS = ROOT / "fixtures" / "ab" / "tasks.json"
DEFAULT_TARGETS = ROOT / "eval_harness" / "ab_targets.json"

def fake_generate_factory(arm_id: str):
    """Deterministic stand-ins for tests: the ungated arms answer, the gated arms refuse."""

    def generate(prompt: str) -> str:
        match = re.search(r"Question:\s*(.+)", prompt)
        question = (match.group(1) if match else prompt).lower()
        if "ukulele" in question:
            return "I do not know." if arm_id in {"previous", "current"} else "Tighten each string to its note."
        if "mongolia" in question:
            return "I do not know." if arm_id in {"previous", "current"} else "The capital is Ulaanbaatar."
        if "gilbert" in question or "behavior engineering" in question:
            return "It distinguishes behavior from accomplishment."
        if "prov-o" in question or "prov:used" in question:
            return "Its domain is activity and its range is entity."
        if "harness" in question:
            return "A harness is a child process that the framework spawns."
        if "primary source" in question:
            return "A primary source relation derives secondary material from a primary source."
        return "I do not know."

    return generate


def live_generate_factory(model: str):
    """One generation per call, with a client built inside the loop.

    The underlying AsyncOpenAI client binds to the event loop that created it,
    and asyncio.run opens a new loop every call. Reusing one client worked for
    the first task and then hung forever on the second, which is why the first
    full run produced an empty log.
    """
    from research_shared.llm import LLMClient, LLMConfig

    # One loop, one client, kept open across calls. The client binds to the loop
    # that created it: asyncio.run per call worked once, then hung on the second
    # task, and a client per call raised "Event loop is closed" during cleanup.
    loop = asyncio.new_event_loop()
    cfg = LLMConfig.from_env()
    cfg.model = model
    client = LLMClient(cfg)

    def generate(prompt: str) -> str:
        return loop.run_until_complete(client.generate(prompt))

    return generate


def http_search(url: str, query: str, limit: int, api_key: str) -> dict:
    body = json.dumps(
        {
            "trace_id": str(uuid.uuid4()),
            "content_type": "claim",
            "parameters": {"query": query, "limit": limit},
            "sources": [],
        }
    ).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/tools/search_knowledge_graph",
        data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": api_key},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    return payload.get("data") or {}


def cmd_run(args: argparse.Namespace) -> int:
    tasks = ab.load_tasks(args.tasks)
    cfg = ab.ArmConfig(
        urls={
            "rag": args.rag_url or args.current_url or "",
            "previous": args.previous_url or "",
            "current": args.current_url or "",
        },
        limit=args.limit,
        model=args.model,
    )

    if args.provider == "fake":
        # Stands in for a corpus passage: carries the facts the tasks require, so a fake
        # run exercises scoring end to end instead of measuring groundedness against noise.
        fake_body = "behavior accomplishment activity entity child process primary source"
        search = lambda url, query, limit: {
            "results": [{"id": "fake", "title": "fake passage", "body": fake_body}],
            "no_strong_evidence": False,
        }
        make_generate = fake_generate_factory
    else:
        search = lambda url, query, limit: http_search(url, query, limit, args.api_key)
        make_generate = live_generate_factory

    live_generate = make_generate(cfg.model) if args.provider == "live" else None
    arms = []
    for arm in ab.ARMS:
        started = time.perf_counter()
        result = ab.run_arm(
            arm, tasks, cfg,
            generate=make_generate(arm.id) if args.provider == "fake" else live_generate,
            search=search,
        )
        result["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
        arms.append(result)
        print(f"[{arm.id}] {result['label']}: {result.get('skipped') or result['summary'].get('success_rate')}")

    by_id = {a["id"]: a["rows"] for a in arms}
    comparisons = {}
    for other in ("rag", "previous", "current"):
        if by_id.get(other) and by_id.get("baseline"):
            comparisons[f"baseline_vs_{other}"] = ab.paired_bootstrap(by_id["baseline"], by_id[other])
    if by_id.get("previous") and by_id.get("current"):
        comparisons["previous_vs_current"] = ab.paired_bootstrap(by_id["previous"], by_id["current"])

    report = {
        "schema_version": ab.SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "config": {
            "model": cfg.model,
            "limit": cfg.limit,
            "tasks": str(args.tasks),
            "release_refs": {"previous": args.previous_ref, "current": args.current_ref},
            "urls": {k: v for k, v in cfg.urls.items() if v},
        },
        "arms": arms,
        "comparisons": comparisons,
        "gate": ab.evaluate_gate({"arms": arms}, json.loads(Path(args.targets).read_text())),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"\nreport: {out}")
    print(f"gate: {report['gate']['verdict']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text())
    print(f"{'arm':<10} {'success':>8} {'abstain':>8} {'ground':>7} {'p95 ms':>8} {'cost $':>9}")
    for arm in report["arms"]:
        if arm.get("skipped"):
            print(f"{arm['id']:<10} skipped: {arm['skipped']}")
            continue
        s = arm["summary"]
        print(
            f"{arm['id']:<10} {s.get('success_rate', 0):>8.2f} "
            f"{(s.get('abstain_accuracy') if s.get('abstain_accuracy') is not None else -1):>8.2f} "
            f"{(s.get('groundedness_mean') if s.get('groundedness_mean') is not None else -1):>7.2f} "
            f"{s.get('latency_p95_ms', 0):>8.0f} {s.get('cost_mean_usd', 0):>9.5f}"
        )
    for name, cmp in report.get("comparisons", {}).items():
        if cmp.get("mean_diff") is None:
            continue
        print(f"{name}: {cmp['mean_diff']:+.3f} CI95 {cmp['ci95']} ({cmp['tasks']} tasks)")
    print(f"\ngate: {report['gate']['verdict']}")
    for check in report["gate"]["checks"]:
        print(f"  [{check['status']}] {check['check']}: {check['detail']}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text())
    targets = json.loads(Path(args.targets).read_text())
    verdict = ab.evaluate_gate(report, targets)
    for check in verdict["checks"]:
        print(f"[{check['status']}] {check['check']}: {check['detail']}")
    print(f"\nverdict: {verdict['verdict']}")
    if verdict["verdict"] == "FAIL":
        return 1
    if verdict["verdict"] == "UNMEASURED":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Four-arm release A/B.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="measure the arms and write a report")
    run.add_argument("--tasks", default=str(DEFAULT_TASKS))
    run.add_argument("--targets", default=str(DEFAULT_TARGETS))
    run.add_argument("--out", required=True)
    run.add_argument("--provider", choices=["fake", "live"], default="live")
    run.add_argument("--api-key", default="")
    run.add_argument("--rag-url", default="")
    run.add_argument("--previous-url", default="")
    run.add_argument("--current-url", default="")
    run.add_argument("--previous-ref", default="")
    run.add_argument("--current-ref", default="")
    # Eight passages: measured groundedness on the 39-task fixture is 0.742 at
    # k=8 against 0.677 at k=5 and 0.710 at k=10, so depth 8 is the best point
    # found rather than a round number.
    run.add_argument("--limit", type=int, default=8)
    run.add_argument("--model", default="deepseek-v4-flash")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="print a report as a table")
    rep.add_argument("--report", required=True)
    rep.set_defaults(func=cmd_report)

    gate = sub.add_parser("gate", help="grade a report against the targets")
    gate.add_argument("--report", required=True)
    gate.add_argument("--targets", default=str(DEFAULT_TARGETS))
    gate.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
