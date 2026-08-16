"""migrations.py — optional schema migrations for the legal plugin.

Migrations are applied once (never on every startup) via a
``schema_migrations`` bookkeeping table, and each migration is written
idempotently (``IF NOT EXISTS``) so re-running is harmless.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def list_migrations() -> list[str]:
    """Return migration file paths in apply order."""
    return sorted(str(p) for p in MIGRATIONS_DIR.glob("*.sql"))


async def apply_schema_migrations(
    db: Any, paths: list[str] | None = None
) -> list[str]:
    """Apply pending migrations to *db* and return the filenames applied.

    *db* is any async object exposing ``execute`` and ``fetchval`` (a
    DatabasePool-like shape).  Applied filenames are recorded in a
    ``schema_migrations`` bookkeeping table so each migration runs exactly
    once.
    """
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " filename TEXT PRIMARY KEY,"
        " applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )

    applied: list[str] = []
    for path in paths if paths is not None else list_migrations():
        filename = Path(path).name
        already = await db.fetchval(
            "SELECT filename FROM schema_migrations WHERE filename = $1",
            filename,
        )
        if already:
            continue
        sql = Path(path).read_text()
        await db.execute(sql)
        await db.execute(
            "INSERT INTO schema_migrations (filename) VALUES ($1)", filename
        )
        applied.append(filename)
    return applied
