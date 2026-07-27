"""auth.py — API key validation, fail-closed authentication.

Every MCP endpoint must validate the caller's API key before processing.
This module provides a simple, testable AuthValidator that rejects
requests when no key is configured or the key is wrong.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# AuthError
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised when authentication fails."""


# ---------------------------------------------------------------------------
# AuthConfig
# ---------------------------------------------------------------------------

@dataclass
class AuthConfig:
    """Authentication configuration.

    Reads from SAIMON_API_KEY and SAIMON_AUTH_HEADER env vars.
    """

    api_key: str | None = None
    header_name: str = "X-Saimon-API-Key"

    @classmethod
    def from_env(cls) -> AuthConfig:
        """Build config from SAIMON_* environment variables."""
        return cls(
            api_key=os.getenv("SAIMON_API_KEY"),
            header_name=os.getenv("SAIMON_AUTH_HEADER", "X-Saimon-API-Key"),
        )


# ---------------------------------------------------------------------------
# AuthValidator
# ---------------------------------------------------------------------------

class AuthValidator:
    """Validates API keys against the configured secret.

    Fail-closed design:
    - If no API key is configured, has_api_key is False.
    - validate() raises AuthError for missing, empty, or wrong keys.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config

    @property
    def has_api_key(self) -> bool:
        """True when an API key has been configured."""
        return bool(self._config.api_key)

    def validate(self, key: str | None) -> None:
        """Check *key* against the configured secret.

        Raises AuthError if the key is missing, empty, or wrong.
        """
        if not key:
            raise AuthError("Missing API key")
        if key != self._config.api_key:
            raise AuthError("Invalid API key")

    def extract_from_headers(self, headers: dict[str, Any]) -> str | None:
        """Pull the API key from request headers (case-insensitive).

        Returns None if the expected header is absent.
        """
        target = self._config.header_name.lower()
        for key, value in headers.items():
            if key.lower() == target:
                return value
        return None
