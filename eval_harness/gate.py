"""Offline eval gate — run every committed fixture suite and pass/fail.

SAIMON-EVAL-CI-GATE-1 (#27): the CI merge/promote signal. Pure and offline —
never touches the network or constructs a live LLM client. A suite passes when
its ``task_success_rate`` meets ``threshold``.
"""

from __future__ import annotations

from . import fixtures as fixtures_mod
from . import runner


def gate_suites(fixtures_root: str, threshold: float = 0.5) -> tuple[bool, list[dict]]:
    """Run all suites under ``fixtures_root`` and return ``(passed, results)``.

    ``passed`` is True only when every suite's task success rate is >=
    ``threshold``. ``results`` is a list of per-suite summaries:
    ``{suite, success_rate, fixtures_run, passed}``.
    """
    suites = fixtures_mod.list_suites(fixtures_root)
    results: list[dict] = []
    passed = True
    for suite in suites:
        report = runner.run_suite(
            fixtures_root, suite, {"success_threshold": threshold}
        )
        summary = report["summary"]
        ok = summary["task_success_rate"] >= threshold
        passed = passed and ok
        results.append(
            {
                "suite": suite,
                "success_rate": summary["task_success_rate"],
                "fixtures_run": summary["fixtures_run"],
                "passed": ok,
            }
        )
    return passed, results
