"""Every DB connection must be attributable (#267 follow-up).

Twelve of seventeen live connections were anonymous in `pg_stat_activity`: when
the pool is exhausted you cannot tell which service did it. The application name
is cheap and it is the difference between a five-minute diagnosis and an outage
postmortem that starts with "some process".
"""

from __future__ import annotations

from research_shared.db import DatabaseConfig


def test_application_name_defaults_to_something_identifiable():
    assert DatabaseConfig().application_name == "saimon"


def test_application_name_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SAIMON_DB_APP_NAME", "verify-mcp")
    assert DatabaseConfig.from_env().application_name == "verify-mcp"


def test_pool_size_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SAIMON_DB_MAX_POOL", "4")
    assert DatabaseConfig.from_env().max_pool_size == 4


def test_pool_budget_stays_under_the_server_limit():
    """7 DB-backed services x default 5 = 35 against max_connections=100.

    This test is a tripwire, not a proof: it fails if someone raises the default
    without doing the arithmetic.
    """
    per_service = DatabaseConfig().max_pool_size
    assert per_service * 7 <= 70
