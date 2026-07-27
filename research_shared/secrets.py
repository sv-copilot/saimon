"""secrets.py — secrets management and startup validation.

Provides SecretsConfig for reading and validating environment-configured
secrets (API keys, database URLs, etc.).  Validation is fail-fast at
startup — if a required secret is missing or a default dev key is used
in production, the service refuses to start.

Usage:
    cfg = SecretsConfig.from_env()
    result = cfg.validate_all(service_name="search-mcp")
    if not result:
        raise RuntimeError(result.summary())
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar

# ---------------------------------------------------------------------------
# SecretRequirement — one secret constraint
# ---------------------------------------------------------------------------

@dataclass
class SecretRequirement:
    """A single secret requirement.

    Attributes:
        key: Environment variable name.
        value: Resolved value from the environment.
        required: If False, failure is never raised (optional secrets).
        default_marker: Prefix/suffix indicating a dev default value.
        production_only: Only enforce in production mode.
        is_production: Whether the current environment is production.
    """

    key: str
    value: str
    required: bool = True
    default_marker: str = "sk-test-"
    production_only: bool = False
    is_production: bool = False

    @property
    def satisfied(self) -> bool:
        if not self.required:
            return True
        if self.production_only and not self.is_production:
            return True
        if not self.value:
            return False
        return not (
            self.default_marker and self.value.startswith(self.default_marker)
        )

    @property
    def missing_msg(self) -> str | None:
        if self.satisfied:
            return None
        if not self.value:
            return f"{self.key}: missing — must be set in environment"
        return f"{self.key}: using default value — must be set to a real secret"


# ---------------------------------------------------------------------------
# ValidationResult — aggregate result for a service
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    service_name: str = ""
    missing: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid

    def summary(self) -> str:
        svc = f"[{self.service_name}] " if self.service_name else ""
        if self.valid:
            return f"{svc}All secrets validated OK."
        header = f"{svc}Secrets validation FAILED ({len(self.missing)} issue(s)):\n"
        return header + "\n".join(f"  - {m}" for m in self.missing)


# ---------------------------------------------------------------------------
# SecretsConfig — the full config object
# ---------------------------------------------------------------------------

@dataclass
class SecretsConfig:
    """All environment-configured secrets for a Saimon MCP service."""

    saimon_api_key: str = ""
    deepseek_api_key: str = ""
    database_url: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    is_production: bool = False

    # Service-specific requirement map:
    # Each MCP declares which secrets it needs at startup.
    _REQUIREMENTS: ClassVar[dict[str, list[tuple[str, bool]]]] = {
        "search-mcp": [("SAIMON_API_KEY", True), ("DATABASE_URL", False)],
        "generate-mcp": [
            ("SAIMON_API_KEY", True),
            ("DEEPSEEK_API_KEY", False),
            ("DATABASE_URL", False),
        ],
        "export-mcp": [("SAIMON_API_KEY", True), ("DATABASE_URL", False)],
        "evaluate-mcp": [
            ("SAIMON_API_KEY", True),
            ("DEEPSEEK_API_KEY", False),
            ("DATABASE_URL", False),
        ],
        "verify-mcp": [
            ("SAIMON_API_KEY", True),
            ("DEEPSEEK_API_KEY", False),
            ("DATABASE_URL", False),
        ],
        "explore-mcp": [("SAIMON_API_KEY", True), ("DATABASE_URL", False)],
    }

    # ------------------------------------------------------------------
    # factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> SecretsConfig:
        return cls(
            saimon_api_key=os.getenv("SAIMON_API_KEY", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            deepseek_base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            is_production=os.getenv("SAIMON_ENV", "").lower() == "production",
        )

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def validate_all(self, service_name: str) -> ValidationResult:
        """Validate all secrets required by *service_name*.

        Returns a ValidationResult that can be used in a boolean context
        and that provides a human-readable summary.
        """
        reqs = self._REQUIREMENTS.get(service_name, [])
        missing: list[str] = []

        for env_key, required in reqs:
            value = getattr(self, self._env_to_attr(env_key), "")
            default_marker = ""
            if env_key == "SAIMON_API_KEY" and self.is_production:
                default_marker = "sk-test-"
            req = SecretRequirement(
                key=env_key,
                value=value,
                required=required,
                default_marker=default_marker,
                is_production=self.is_production,
            )
            msg = req.missing_msg
            if msg is not None:
                missing.append(msg)

        return ValidationResult(
            valid=len(missing) == 0,
            service_name=service_name,
            missing=missing,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _env_to_attr(env_key: str) -> str:
        """Map environment variable name to SecretsConfig attribute name."""
        mapping: dict[str, str] = {
            "SAIMON_API_KEY": "saimon_api_key",
            "DEEPSEEK_API_KEY": "deepseek_api_key",
            "DATABASE_URL": "database_url",
            "DEEPSEEK_BASE_URL": "deepseek_base_url",
        }
        return mapping.get(env_key, env_key.lower())
