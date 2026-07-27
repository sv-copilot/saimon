"""db.py — PostgreSQL connection pool wrapper.

Provides an async connection pool over asyncpg.  Reads configuration
from environment variables.  Fail-closed: refuses to initialise
without a database URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Build config from SAIMON_* environment variables."""
        return cls(
            database_url=os.getenv("SAIMON_DATABASE_URL"),
            min_pool_size=int(os.getenv("SAIMON_DB_MIN_POOL", "2")),
            max_pool_size=int(os.getenv("SAIMON_DB_MAX_POOL", "10")),
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
                "Set SAIMON_DATABASE_URL in the environment."
            )
        self.config = config
        self._pool: Any = None

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a SQL statement and return the status message."""
        raise NotImplementedError("DatabasePool requires a live PostgreSQL connection.")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Run a query and return all rows as dicts."""
        raise NotImplementedError("DatabasePool requires a live PostgreSQL connection.")

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        """Run a query and return the first row as a dict, or None."""
        raise NotImplementedError("DatabasePool requires a live PostgreSQL connection.")

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Run a query and return the first column of the first row."""
        raise NotImplementedError("DatabasePool requires a live PostgreSQL connection.")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
