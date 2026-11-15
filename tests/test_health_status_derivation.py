"""A /health body must not say ok while one of its checks says a dependency is unavailable.

The bug this pins: five services reported {"status": "ok", "checks": {"database": "unavailable"}}
for twenty hours. Any monitor reading the status field saw green.
"""

from research_shared.health import derive_status, finalize_health


def test_unavailable_database_degrades_the_status():
    assert derive_status({"database": "unavailable"}) == "degraded"


def test_connected_database_is_ok():
    assert derive_status({"database": "connected"}) == "ok"


def test_counts_and_free_text_are_not_failures():
    checks = {"database": "connected", "kg_nodes": 0, "plugins": 1, "note": "warming up"}
    assert derive_status(checks) == "ok"


def test_nested_checks_are_inspected():
    assert derive_status({"deps": {"llm": "timeout"}}) == "degraded"


def test_failure_vocabulary_is_case_insensitive():
    assert derive_status({"database": "Unavailable"}) == "degraded"
    assert derive_status({"database": "NOT CONNECTED"}) == "degraded"


def test_finalize_health_overwrites_a_hardcoded_ok():
    body = {"status": "ok", "service": "search-mcp", "checks": {"database": "unavailable"}}
    assert finalize_health(body)["status"] == "degraded"


def test_finalize_health_tolerates_a_body_without_checks():
    assert finalize_health({"status": "ok"})["status"] == "ok"
