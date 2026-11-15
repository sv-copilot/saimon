"""lifespan.py — shared FastAPI lifespan for startup validation + graceful shutdown.

Provides a context-manager-based lifespan that:
1. Validates secrets at startup (fail-fast, refuses to start if missing).
2. Registers shutdown handlers for DB pools, LLM clients, and other
   long-lived resources.
3. Returns a state dict that endpoints can access via request.state.

Usage in each MCP server.py:

    from research_shared.lifespan import build_lifespan

    _lifespan = build_lifespan(
        service_name="search-mcp",
        db_pool_ref=lambda: _db_pool,
    )
    app = FastAPI(title="search-mcp", lifespan=_lifespan)
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from research_shared.secrets import SecretsConfig

logger = logging.getLogger("saimon.lifespan")


# ---------------------------------------------------------------------------
# build_lifespan
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# database connection
# ---------------------------------------------------------------------------

# A service that starts while PostgreSQL is still accepting connections used to give up on
# its first failure and run degraded until someone restarted it. It now keeps trying, so a
# slow database costs seconds of degraded status instead of a day.
_DB_RECONNECT_MIN_SECONDS = 1.0
_DB_RECONNECT_MAX_SECONDS = 30.0


async def _connect_db(
    db_url: str, service_name: str, setter: Callable[[Any], None]
) -> Any:
    """Open a verified pool, hand it to the service, and wire the audit logger."""
    from research_shared.db import DatabaseConfig, DatabasePool

    # Pool budget: seven DB-backed services x 5 = 35 connections against
    # max_connections=100, leaving room for Metabase and psql. Raise per service via
    # SAIMON_DB_MAX_POOL only with that arithmetic in mind.
    cfg = DatabaseConfig(
        database_url=db_url,
        min_pool_size=int(os.getenv("SAIMON_DB_MIN_POOL", "1")),
        max_pool_size=int(os.getenv("SAIMON_DB_MAX_POOL", "5")),
        application_name=service_name,
    )
    pool = DatabasePool(cfg)
    await pool.fetch("SELECT 1")  # triggers lazy init + verifies
    setter(pool)

    from research_shared.audit import set_audit_db_pool

    set_audit_db_pool(pool)
    return pool


async def _reconnect_db_until_connected(
    db_url: str, service_name: str, setter: Callable[[Any], None]
) -> None:
    """Retry the pool until it connects. Cancelled at shutdown, never on failure."""
    delay = float(os.getenv("SAIMON_DB_RECONNECT_MIN_SECONDS", _DB_RECONNECT_MIN_SECONDS))
    cap = float(os.getenv("SAIMON_DB_RECONNECT_MAX_SECONDS", _DB_RECONNECT_MAX_SECONDS))
    attempt = 0
    while True:
        attempt += 1
        try:
            await _connect_db(db_url, service_name, setter)
            # Warning, not info: a service that spent time degraded has recovered, and that
            # is worth seeing in a log an operator actually reads.
            logger.warning(
                "%s DB pool connected on retry attempt %d — recovered from degraded startup",
                service_name, attempt,
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s DB reconnect attempt %d failed: %s — next attempt in %.1fs",
                service_name, attempt, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, cap)


def build_lifespan(
    service_name: str,
    *,
    db_pool_ref: Callable[..., Any] | None = None,
    db_pool_setter: Callable[[Any], None] | None = None,
    llm_client_ref: Callable[..., Any] | None = None,
    llm_client_setter: Callable[[Any], None] | None = None,
) -> Callable[[FastAPI], Any]:
    """Create an ASGI lifespan context manager for *service_name*.

    Parameters:
        service_name: e.g. "search-mcp", "generate-mcp".
        db_pool_ref: Optional callable returning the current DatabasePool.
        db_pool_setter: Optional callable to inject a new DatabasePool.
        llm_client_ref: Optional callable returning the current LLMClient.
        llm_client_setter: Optional callable to inject a new LLMClient.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ── startup ──────────────────────────────────────────
        logger.info("%s starting up", service_name)

        # Validate secrets — refuse to start if missing.
        cfg = SecretsConfig.from_env()
        result = cfg.validate_all(service_name)
        if not result:
            logger.error(result.summary())
            raise RuntimeError(result.summary())

        logger.info("%s secrets validated OK", service_name)

        # Store config on app state for /health checks.
        app.state.service_name = service_name
        app.state.secrets_config = cfg

        # ── auto-connect DB pool ─────────────────────────────
        if db_pool_setter is not None:
            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                try:
                    await _connect_db(db_url, service_name, db_pool_setter)
                    logger.info("%s DB pool connected", service_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s DB pool unavailable: %s — retrying in the background",
                        service_name, exc,
                    )
                    app.state.db_reconnect_task = asyncio.create_task(
                        _reconnect_db_until_connected(db_url, service_name, db_pool_setter)
                    )
            else:
                logger.info("%s no DATABASE_URL — running without DB", service_name)

        # ── auto-connect LLM client ───────────────────────────
        if llm_client_setter is not None:
            llm_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if llm_key:
                try:
                    from research_shared.llm import LLMClient, LLMConfig

                    llm_cfg = LLMConfig.from_env()
                    llm = LLMClient(llm_cfg)
                    await llm.health_check()
                    llm_client_setter(llm)
                    logger.info("%s LLM client connected", service_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s LLM client unavailable: %s — running degraded",
                        service_name, exc,
                    )
            else:
                logger.info("%s no DEEPSEEK_API_KEY — running without LLM", service_name)

        # ── yield to application ─────────────────────────────
        yield

        # ── shutdown ─────────────────────────────────────────
        logger.info("%s shutting down", service_name)

        # Stop the reconnect loop before closing anything it might hand over.
        task = getattr(app.state, "db_reconnect_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close DB pool if injected.
        if db_pool_ref is not None:
            pool = db_pool_ref()
            if pool is not None:
                try:
                    await pool.close()
                    logger.info("%s DB pool closed", service_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s DB pool close error: %s", service_name, exc)

        # Close LLM client if injected.
        if llm_client_ref is not None:
            client = llm_client_ref()
            if client is not None and hasattr(client, "close"):
                try:
                    await client.close()
                    logger.info("%s LLM client closed", service_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s LLM client close error: %s", service_name, exc
                    )

        logger.info("%s shutdown complete", service_name)

    return lifespan
