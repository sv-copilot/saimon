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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_harness.compare import compare_reports
from eval_harness.runner import run_suite, write_report


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
