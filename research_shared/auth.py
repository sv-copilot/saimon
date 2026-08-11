"""auth.py — API key validation, multi-key support, key rotation.

Every MCP endpoint must validate the caller's API key before processing.
This module provides a simple, testable AuthValidator that rejects
requests when no key is configured or the key is wrong.

Supports:
- Multiple valid API keys per service (comma-separated SAIMON_API_KEY)
- Key rotation with overlap period (SAIMON_API_KEY_OLD + SAIMON_API_KEY)
- Key hashing for audit trail (SHA-256, first 8 hex chars)
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
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

    Reads from SAIMON_API_KEY, SAIMON_API_KEY_OLD, and SAIMON_AUTH_HEADER
    env vars.  Supports comma-separated keys for multi-key deployments.
    """

    api_keys: set[str] = field(default_factory=set)
    old_api_keys: set[str] = field(default_factory=set)
    header_name: str = "X-Saimon-API-Key"
    rotation_overlap_seconds: int = 3600  # 1 hour default

    @classmethod
    def from_env(cls) -> AuthConfig:
        """Build config from SAIMON_* environment variables."""
        keys_raw = os.getenv("SAIMON_API_KEY", "")
        old_keys_raw = os.getenv("SAIMON_API_KEY_OLD", "")

        api_keys: set[str] = set()
        if keys_raw:
            for k in keys_raw.split(","):
                k = k.strip()
                if k:
                    api_keys.add(k)

        old_api_keys: set[str] = set()
        if old_keys_raw:
            for k in old_keys_raw.split(","):
                k = k.strip()
                if k:
                    old_api_keys.add(k)

        rotation_overlap = int(
            os.getenv("SAIMON_KEY_ROTATION_OVERLAP", "3600")
        )

        return cls(
            api_keys=api_keys,
            old_api_keys=old_api_keys,
            header_name=os.getenv("SAIMON_AUTH_HEADER", "X-Saimon-API-Key"),
            rotation_overlap_seconds=rotation_overlap,
        )


# ---------------------------------------------------------------------------
# key hashing utility
# ---------------------------------------------------------------------------

def hash_key(key: str) -> str:
    """Return a short hash of *key* for audit trails.

    Uses SHA-256, truncates to first 8 hex characters.
    """
    return hashlib.sha256(key.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# AuthValidator
# ---------------------------------------------------------------------------

class AuthValidator:
    """Validates API keys against configured secrets.

    Fail-closed design:
    - If no API key is configured, has_api_key is False.
    - validate() raises AuthError for missing, empty, or wrong keys.
    - Supports multiple valid keys (comma-separated).
    - Supports key rotation with overlap via SAIMON_API_KEY_OLD.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._rotation_start: float | None = None
        if config.old_api_keys:
            self._rotation_start = time.monotonic()

    @property
    def has_api_key(self) -> bool:
        """True when at least one API key has been configured."""
        return bool(self._config.api_keys or self._config.old_api_keys)

    @property
    def active_key_count(self) -> int:
        """Number of currently valid API keys (for testing)."""
        count = len(self._config.api_keys)
        if self._old_keys_still_valid():
            count += len(self._config.old_api_keys)
        return count

    def _old_keys_still_valid(self) -> bool:
        """Check if old keys are still within the rotation overlap window."""
        if not self._config.old_api_keys or self._rotation_start is None:
            return False
        elapsed = time.monotonic() - self._rotation_start
        return elapsed < self._config.rotation_overlap_seconds

    def validate(self, key: str | None) -> str:
        """Check *key* against configured secrets.

        Raises AuthError if the key is missing, empty, or wrong.
        Returns the matched key on success.
        """
        if not key:
            raise AuthError("Missing API key")

        # Check active keys first
        if key in self._config.api_keys:
            return key

        # Check old keys during rotation overlap
        if self._old_keys_still_valid() and key in self._config.old_api_keys:
            return key

        raise AuthError("Invalid API key")

    def hash_for_audit(self, key: str | None) -> str:
        """Return a hashed key suitable for audit logging.

        Returns 'anonymous' if key is None.
        """
        if not key:
            return "anonymous"
        return hash_key(key)

    def extract_from_headers(self, headers: dict[str, Any]) -> str | None:
        """Pull the API key from request headers (case-insensitive).

        Returns None if the expected header is absent.
        """
        target = self._config.header_name.lower()
        for key, value in headers.items():
            if key.lower() == target:
                return value
        return None

