"""A service that starts before PostgreSQL must recover without a restart.

Previously the pool was attempted once; when Postgres was still starting, the service logged
"running degraded" and stayed that way until someone restarted the container.
"""

import asyncio

import pytest

from research_shared import lifespan as lifespan_mod


@pytest.mark.asyncio
async def test_reconnect_loop_retries_until_a_connection_succeeds(monkeypatch):
    monkeypatch.setenv("SAIMON_DB_RECONNECT_MIN_SECONDS", "0")
    monkeypatch.setenv("SAIMON_DB_RECONNECT_MAX_SECONDS", "0")

    attempts = []
    handed_over = []

    async def flaky_connect(db_url, service_name, setter):
        attempts.append(service_name)
        if len(attempts) < 3:
            raise OSError("Connection refused")
        setter("pool")
        return "pool"

    monkeypatch.setattr(lifespan_mod, "_connect_db", flaky_connect)

    await asyncio.wait_for(
        lifespan_mod._reconnect_db_until_connected(
            "postgresql://example/db", "search-mcp", handed_over.append
        ),
        timeout=5,
    )

    assert len(attempts) == 3, "the loop stopped before the connection succeeded"
    assert handed_over == ["pool"], "a successful connection was not handed to the service"


@pytest.mark.asyncio
async def test_reconnect_loop_is_cancellable_at_shutdown(monkeypatch):
    monkeypatch.setenv("SAIMON_DB_RECONNECT_MIN_SECONDS", "0")
    monkeypatch.setenv("SAIMON_DB_RECONNECT_MAX_SECONDS", "0")

    async def always_fails(db_url, service_name, setter):
        raise OSError("Connection refused")

    monkeypatch.setattr(lifespan_mod, "_connect_db", always_fails)

    task = asyncio.create_task(
        lifespan_mod._reconnect_db_until_connected("postgresql://example/db", "x-mcp", lambda _: None)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
