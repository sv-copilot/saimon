"""Diff two run reports and declare regressions."""

from __future__ import annotations


def compare_reports(
    report_a: dict,
    report_b: dict,
    quality_threshold: float = 0.05,
    fail_on_success_drop: bool = True,
) -> dict:
    """Compare two run reports fixture-by-fixture.

    A fixture is a regression when its quality drops by more than
    ``quality_threshold`` or (optionally) its ``task_success`` flips from
    True to False. Returns a result dict with a ``verdict`` of ``REGRESSION``
    or ``OK`` and the list of regressed fixture ids.
    """
    a = {f["id"]: f for f in report_a.get("fixtures", [])}
    b = {f["id"]: f for f in report_b.get("fixtures", [])}

    diffs: list[dict] = []
    regressions: list[str] = []
    for fixture_id in sorted(set(a) | set(b)):
        fa, fb = a.get(fixture_id), b.get(fixture_id)
        if fa is None or fb is None:
            diffs.append(
                {
                    "id": fixture_id,
                    "metrics_a": fa,
                    "metrics_b": fb,
                    "delta": {},
                    "regressed": True,
                    "reason": "missing in one report",
                }
            )
            regressions.append(fixture_id)
            continue

        quality_delta = round(fb["quality"] - fa["quality"], 4)
        success_dropped = bool(fa["task_success"]) and not bool(fb["task_success"])
        quality_regressed = fb["quality"] < fa["quality"] - quality_threshold
        regressed = quality_regressed or (fail_on_success_drop and success_dropped)

        reason = ""
        if success_dropped and fail_on_success_drop:
            reason = "task success dropped"
        elif quality_regressed:
            reason = "quality regression"

        delta = {
            "quality": quality_delta,
            "task_success": success_dropped,
            "cost": fb["cost"] - fa["cost"],
            "latency_ms": round(fb["latency_ms"] - fa["latency_ms"], 4),
        }
        entry = {
            "id": fixture_id,
            "metrics_a": fa,
            "metrics_b": fb,
            "delta": delta,
            "regressed": regressed,
        }
        if reason:
            entry["reason"] = reason
        diffs.append(entry)
        if regressed:
            regressions.append(fixture_id)

    return {
        "fixtures": diffs,
        "regressions": regressions,
        "verdict": "REGRESSION" if regressions else "OK",
    }
