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

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from research_shared.secrets import SecretsConfig

logger = logging.getLogger("saimon.lifespan")


# ---------------------------------------------------------------------------
# build_lifespan
# ---------------------------------------------------------------------------


def build_lifespan(
    service_name: str,
    *,
    db_pool_ref: Callable[..., Any] | None = None,
    llm_client_ref: Callable[..., Any] | None = None,
) -> Callable[[FastAPI], Any]:
    """Create an ASGI lifespan context manager for *service_name*.

    Parameters:
        service_name: e.g. "search-mcp", "generate-mcp".
        db_pool_ref: Optional callable returning the current DatabasePool.
        llm_client_ref: Optional callable returning the current LLMClient.
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

        # ── yield to application ─────────────────────────────
        yield

        # ── shutdown ─────────────────────────────────────────
        logger.info("%s shutting down", service_name)

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
