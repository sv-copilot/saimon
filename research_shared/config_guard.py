"""Refusals for configuration that would otherwise degrade quietly.

The API used to fall back to a development JWT secret whenever
``SAIMON_JWT_SECRET`` was missing, including in production. A missing variable
then produced a working service signing tokens with a value that is published in
this repository, and nothing in the logs said so.

The rule here: in production, missing or default is a startup failure. A secret
that is present but short is a warning, because rotating it mid-flight
invalidates every issued token and that is an operator decision, not a boot
decision.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

DEV_SECRET = "dev-secret-change-in-prod"
MIN_SECRET_BYTES = 32
_PRODUCTION_NAMES = frozenset({"production", "prod"})

logger = logging.getLogger("saimon.config")


def resolve_jwt_secret(
    *,
    env: str | None = None,
    getenv: Callable[[str, str], str] = os.environ.get,
) -> str:
    """The JWT secret, or a refusal when production has none.

    ``env`` and ``getenv`` are injectable so the rule can be tested without
    mutating the process environment.
    """
    environment = (env if env is not None else getenv("SAIMON_ENV", "")).strip().lower()
    production = environment in _PRODUCTION_NAMES
    secret = (getenv("SAIMON_JWT_SECRET", "") or "").strip()

    if not secret or secret == DEV_SECRET:
        if production:
            raise RuntimeError(
                "SAIMON_JWT_SECRET is unset or still the development default while "
                "SAIMON_ENV=production. Refusing to sign tokens with a published "
                "secret; set a random value of at least 32 bytes."
            )
        return DEV_SECRET

    if len(secret.encode()) < MIN_SECRET_BYTES:
        logger.warning(
            "SAIMON_JWT_SECRET is %d bytes, below the %d-byte minimum for HS256. "
            "Tokens still verify; rotate when it is safe to invalidate sessions.",
            len(secret.encode()),
            MIN_SECRET_BYTES,
        )
    return secret
