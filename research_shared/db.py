"""db.py — PostgreSQL connection pool wrapper.

Provides an async connection pool over asyncpg.  Reads configuration
from environment variables.  Fail-closed: refuses to initialise
without a database URL.

When DATABASE_URL is set, methods connect to a live PostgreSQL instance.
When not set, methods raise NotImplementedError (fail-closed).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("saimon.db")

# ---------------------------------------------------------------------------
# DatabaseError
# ---------------------------------------------------------------------------

class DatabaseError(Exception):
    """Raised when a database operation fails."""


# ---------------------------------------------------------------------------
# DatabaseConfig
# ---------------------------------------------------------------------------

@dataclass
class DatabaseConfig:
    """PostgreSQL connection configuration.

    All values can be set via environment variables.
    """

    database_url: str | None = None
    min_pool_size: int = 2
    max_pool_size: int = 10
    # Without this every MCP service is anonymous in pg_stat_activity, so an
    # exhausted pool cannot be attributed to the service that exhausted it.
    application_name: str = "saimon"

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Build config from SAIMON_* environment variables."""
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            min_pool_size=int(os.getenv("SAIMON_DB_MIN_POOL", "2")),
            max_pool_size=int(os.getenv("SAIMON_DB_MAX_POOL", "10")),
            application_name=os.getenv("SAIMON_DB_APP_NAME", "saimon"),
        )

    def __repr__(self) -> str:
        """Safe repr that masks the password in the URL."""
        url = self.database_url
        if url and "@" in url:
            # Mask password between : and @
            prefix, rest = url.split("@", 1)
            if "://" in prefix:
                scheme, remainder = prefix.split("://", 1)
                if ":" in remainder:
                    user, _pwd = remainder.rsplit(":", 1)
                    safe_prefix = f"{scheme}://{user}:***"
                else:
                    safe_prefix = prefix
            else:
                safe_prefix = "***"
            safe_url = f"{safe_prefix}@{rest}"
        else:
            safe_url = url
        return (
            f"DatabaseConfig(database_url={safe_url!r}, "
            f"min_pool_size={self.min_pool_size}, "
            f"max_pool_size={self.max_pool_size})"
        )


# ---------------------------------------------------------------------------
# pgvector codec (SAIMON-PGVECTOR-CODEC-1)
# ---------------------------------------------------------------------------

def _encode_vector(value: Any) -> str:
    """Encode a Python list[float] (or existing string) as a pgvector text literal.

    asyncpg has no built-in codec for the pgvector ``vector`` type, so passing
    a ``list[float]`` as a query parameter raises ``DatabaseError: expected
    str, got list``.  Encoding to the text form ``[1.0,2.0,3.0]`` lets the
    server-side cast from text to vector succeed.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(str(float(v)) for v in value) + "]"
    return str(value)


def _decode_vector(value: Any) -> Any:
    """Decode a pgvector text literal back into a list[float]."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if inner:
                return [float(v) for v in inner.split(",")]
            return []
    return value


async def _register_pgvector_codec(conn: Any) -> None:
    """Register the pgvector ``vector`` codec on a new asyncpg connection.

    Fail-closed: if the vector type is unavailable (extension missing) or
    codec registration fails, the connection is left untouched and callers
    fall back to keyword search.
    """
    try:
        row = await conn.fetchrow(
            "SELECT t.typname, n.nspname "
            "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE t.oid = 'vector'::regtype::oid"
        )
    except Exception:  # noqa: BLE001 — vector extension unavailable
        return
    if row is None:
        return
    try:
        await conn.set_type_codec(
            row["typname"],
            schema=row["nspname"],
            encoder=_encode_vector,
            decoder=_decode_vector,
            format="text",
        )
    except Exception:  # noqa: BLE001 — codec registration best-effort
        return


# ---------------------------------------------------------------------------
# DatabasePool
# ---------------------------------------------------------------------------

class DatabasePool:
    """Async connection pool wrapper for PostgreSQL via asyncpg.

    Fail-closed: raises DatabaseError if constructed without a database URL.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        if not config.database_url:
            raise DatabaseError(
                "DatabasePool requires a database URL. "
                "Set DATABASE_URL in the environment."
            )
        self.config = config
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        """Lazy-init the asyncpg connection pool."""
        if self._pool is None:
            try:
                import asyncpg
            except ImportError:
                raise DatabaseError(
                    "asyncpg package is required for live DB connections. "
                    "Install with: pip install asyncpg"
                )
            self._pool = await asyncpg.create_pool(
                self.config.database_url,
                min_size=self.config.min_pool_size,
                max_size=self.config.max_pool_size,
                init=_register_pgvector_codec,
                server_settings={"application_name": self.config.application_name},
            )
        return self._pool

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a SQL statement and return the status message."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(query, *args)
                return result
        except ImportError:
            raise NotImplementedError(
                "DatabasePool.execute requires asyncpg. "
                "Install with: pip install asyncpg"
            )
        except Exception as exc:
            logger.error("DB execute failed: %s", exc)
            raise DatabaseError(str(exc)) from exc

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Run a query and return all rows as dicts."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(r) for r in rows]
        except ImportError:
            raise NotImplementedError(
                "DatabasePool.fetch requires asyncpg. "
                "Install with: pip install asyncpg"
            )
        except Exception as exc:
            logger.error("DB fetch failed: %s", exc)
            raise DatabaseError(str(exc)) from exc

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        """Run a query and return the first row as a dict, or None."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None
        except ImportError:
            raise NotImplementedError(
                "DatabasePool.fetchrow requires asyncpg. "
                "Install with: pip install asyncpg"
            )
        except Exception as exc:
            logger.error("DB fetchrow failed: %s", exc)
            raise DatabaseError(str(exc)) from exc

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Run a query and return the first column of the first row."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        except ImportError:
            raise NotImplementedError(
                "DatabasePool.fetchval requires asyncpg. "
                "Install with: pip install asyncpg"
            )
        except Exception as exc:
            logger.error("DB fetchval failed: %s", exc)
            raise DatabaseError(str(exc)) from exc

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def transaction(self):
        """Async context manager for transactional work.

        Acquires a connection from the pool, starts a transaction,
        yields the connection, and commits on success or rolls back
        on exception.

        Usage:
            async with db.transaction() as conn:
                await conn.execute("INSERT INTO ...")
                await conn.execute("UPDATE ...")
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            yield conn

    @asynccontextmanager
    async def acquire(self) -> Any:
        """Acquire a raw asyncpg connection from the pool.

        Yields the connection for callers that need connection-level
        operations (e.g. ``saimon_mcp.explore.gap_sweep.list_gaps``, which
        uses ``conn.fetch`` / ``conn.fetchval`` directly).
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            yield conn
