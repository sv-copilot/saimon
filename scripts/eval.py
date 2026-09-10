#!/usr/bin/env python3
"""Offline A/B eval harness CLI.

Usage:
    python3 scripts/eval.py run --suite generation --config fixtures/generation/default.json
    python3 scripts/eval.py compare report-a.json report-b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_harness.compare import compare_reports
from eval_harness.gate import gate_suites
from eval_harness.runner import run_suite, write_report
from research_shared.model_ab_gate import ROUTE_TIERS, gate_current_routing


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text())


def cmd_run(args: argparse.Namespace) -> int:
    config_path = args.config_flag or args.config
    config = _load_json(config_path) if config_path else None
    report = run_suite(args.fixtures_root, args.suite, config)
    if args.output:
        write_report(report, args.output)
        print(f"report written to {args.output}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    report_a = _load_json(args.report_a)
    report_b = _load_json(args.report_b)
    result = compare_reports(
        report_a,
        report_b,
        quality_threshold=args.threshold,
        fail_on_success_drop=not args.no_fail_on_success,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["regressions"] else 0


def cmd_gate(args: argparse.Namespace) -> int:
    """Run every committed fixture suite offline; fail on any below threshold."""
    passed, results = gate_suites(args.fixtures_root, threshold=args.threshold)
    print(json.dumps({"passed": passed, "suites": results}, indent=2, ensure_ascii=False))
    return 0 if passed else 1


def cmd_ab(args: argparse.Namespace) -> int:
    """Run an offline A/B for a route/tier and record the verdict.

    Scores the incumbent and candidate fixture outputs for the affected tier,
    diffs them with the same engine as ``eval.py compare``, and records the
    result in ``model_ab_verdict.json``. A green (``OK``) result promotes the
    candidate to the route's incumbent; a regression is recorded but does not.
    """
    tier = args.tier or ROUTE_TIERS.get(args.route)
    if not tier:
        print(
            f"unknown route {args.route!r}; pass --tier explicitly", file=sys.stderr
        )
        return 2

    incumbent_report = run_suite(
        args.fixtures_root, tier, {"candidate_key": args.incumbent_key}
    )
    candidate_report = run_suite(
        args.fixtures_root, tier, {"candidate_key": args.candidate_key}
    )
    result = compare_reports(
        incumbent_report,
        candidate_report,
        quality_threshold=args.threshold,
    )

    verdict_path = Path(args.output)
    if verdict_path.exists():
        doc = _load_json(str(verdict_path))
    else:
        doc = {"version": 1, "incumbents": {}, "verdicts": []}
    doc.setdefault("incumbents", {})
    doc.setdefault("verdicts", [])

    entry = {
        "route": args.route,
        "tier": tier,
        "incumbent": args.incumbent_model,
        "candidate": args.candidate_model,
        "verdict": result["verdict"],
        "method": "eval.py compare",
        "compare": {
            "verdict": result["verdict"],
            "regressions": result["regressions"],
        },
        "compare_command": (
            f"python3 scripts/eval.py ab --route {args.route} "
            f"--incumbent-model {args.incumbent_model} "
            f"--candidate-model {args.candidate_model}"
        ),
        "committed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Replace any prior verdict for the same route/incumbent/candidate.
    doc["verdicts"] = [
        v
        for v in doc["verdicts"]
        if not (
            v.get("route") == args.route
            and v.get("incumbent") == args.incumbent_model
            and v.get("candidate") == args.candidate_model
        )
    ]
    doc["verdicts"].append(entry)

    if result["verdict"] == "OK":
        doc["incumbents"][args.route] = args.candidate_model

    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    print(json.dumps(entry, indent=2, ensure_ascii=False))
    print(f"verdict recorded to {verdict_path}")
    return 1 if result["regressions"] else 0


def cmd_gate_model(args: argparse.Namespace) -> int:
    """Enforce the model-routing A/B gate against the committed verdict doc."""
    decision = gate_current_routing(args.verdict)
    print(
        json.dumps(
            {"allowed": decision.allowed, "reasons": decision.reasons},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if decision.allowed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval.py", description="Offline A/B eval harness"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a fixture suite and write a JSON report")
    run_p.add_argument("config", nargs="?", help="path to a config JSON (positional)")
    run_p.add_argument("--config", dest="config_flag", help="path to a config JSON")
    run_p.add_argument("--suite", required=True, help="suite name under fixtures/")
    run_p.add_argument("--fixtures-root", default="fixtures", help="fixtures dir")
    run_p.add_argument("--output", help="write report to this path instead of stdout")
    run_p.set_defaults(func=cmd_run)

    cmp_p = sub.add_parser("compare", help="compare two run reports")
    cmp_p.add_argument("report_a", help="baseline report JSON")
    cmp_p.add_argument("report_b", help="candidate report JSON")
    cmp_p.add_argument("--threshold", type=float, default=0.05, help="quality drop threshold")
    cmp_p.add_argument(
        "--no-fail-on-success",
        action="store_true",
        help="ignore task_success True->False drops",
    )
    cmp_p.set_defaults(func=cmd_compare)

    gate_p = sub.add_parser("gate", help="run all fixture suites; fail below threshold")
    gate_p.add_argument("--fixtures-root", default="fixtures", help="fixtures dir")
    gate_p.add_argument(
        "--threshold", type=float, default=0.5, help="task success rate threshold"
    )
    gate_p.set_defaults(func=cmd_gate)

    ab_p = sub.add_parser(
        "ab", help="run offline A/B for a route/tier and record a verdict"
    )
    ab_p.add_argument("--route", required=True, help="route key, e.g. saimon.generate")
    ab_p.add_argument("--tier", help="fixture suite name (defaults from route)")
    ab_p.add_argument("--incumbent-model", required=True, help="incumbent model slug")
    ab_p.add_argument("--candidate-model", required=True, help="candidate model slug")
    ab_p.add_argument(
        "--incumbent-key", default="incumbent", help="fixture field for incumbent output"
    )
    ab_p.add_argument(
        "--candidate-key", default="candidate", help="fixture field for candidate output"
    )
    ab_p.add_argument("--fixtures-root", default="fixtures", help="fixtures dir")
    ab_p.add_argument("--threshold", type=float, default=0.05, help="quality drop threshold")
    ab_p.add_argument(
        "--output", default="model_ab_verdict.json", help="verdict document path"
    )
    ab_p.set_defaults(func=cmd_ab)

    gate_model_p = sub.add_parser(
        "gate-model", help="enforce the model-routing A/B gate"
    )
    gate_model_p.add_argument(
        "--verdict", default="model_ab_verdict.json", help="verdict document path"
    )
    gate_model_p.set_defaults(func=cmd_gate_model)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
