"""The watchdog must read the service's own claim, not the process's presence."""

from __future__ import annotations

from scripts.watchdog import classify, transitions

OK = {"status": "ok", "checks": {"database": "connected"}}
NO_DB = {"status": "ok", "checks": {"database": "unavailable"}}
DEGRADED = {"status": "degraded", "checks": {"database": "connected"}}


def test_ok_requires_both_a_claim_and_a_database() -> None:
    assert classify(OK) == "ok"


def test_healthy_status_without_a_database_is_degraded() -> None:
    # The twenty-hour failure: status said ok, database said unavailable.
    assert classify(NO_DB) == "degraded"


def test_degraded_status_is_degraded() -> None:
    assert classify(DEGRADED) == "degraded"


def test_no_response_is_down() -> None:
    assert classify(None, "connection refused") == "down"


def test_first_run_reports_only_problems() -> None:
    changes = transitions({}, {"search": "ok", "verify": "degraded", "api": "down"})
    assert ("verify", "unknown", "degraded") in changes
    assert ("api", "unknown", "down") in changes
    assert not any(service == "search" for service, _, _ in changes)


def test_a_repeated_state_is_not_re_announced() -> None:
    assert transitions({"verify": "degraded"}, {"verify": "degraded"}) == []


def test_recovery_is_announced() -> None:
    assert transitions({"verify": "degraded"}, {"verify": "ok"}) == [
        ("verify", "degraded", "ok")
    ]


def test_a_service_without_a_database_is_healthy_when_nothing_fails() -> None:
    assert classify({"status": "ok", "checks": {"backend": "stateless"}}) == "ok"
    assert classify({"status": "ok", "checks": {"llm": "connected"}}) == "ok"


def test_any_failing_check_degrades_the_service() -> None:
    assert classify({"status": "ok", "checks": {"llm": "disconnected"}}) == "degraded"
    assert classify({"status": "ok", "checks": {"database": "connected",
                                                "cache": "error"}}) == "degraded"
