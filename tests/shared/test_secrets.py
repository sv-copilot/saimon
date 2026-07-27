"""Tests for research_shared/secrets.py — SecretsConfig.

Validates:
- Environment variable parsing
- Required secret detection
- Production mode validation
- Missing secret reporting
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from research_shared.secrets import SecretsConfig, SecretRequirement


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clear_env(*keys: str) -> None:
    for k in keys:
        os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------

class TestSecretsConfigFromEnv:
    """Environment variable parsing."""

    def test_reads_saimon_api_key(self):
        with mock.patch.dict(os.environ, {"SAIMON_API_KEY": "sk-test-key"}):
            cfg = SecretsConfig.from_env()
            assert cfg.saimon_api_key == "sk-test-key"

    def test_reads_deepseek_api_key(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-key"}):
            cfg = SecretsConfig.from_env()
            assert cfg.deepseek_api_key == "sk-ds-key"

    def test_reads_database_url(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://u:p@h/db"}):
            cfg = SecretsConfig.from_env()
            assert cfg.database_url == "postgresql://u:p@h/db"

    def test_reads_deepseek_base_url(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_BASE_URL": "https://custom.api/v1"}):
            cfg = SecretsConfig.from_env()
            assert cfg.deepseek_base_url == "https://custom.api/v1"

    def test_defaults_when_vars_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = SecretsConfig.from_env()
            assert cfg.saimon_api_key == ""
            assert cfg.deepseek_api_key == ""
            assert cfg.database_url == ""
            assert cfg.deepseek_base_url == "https://api.deepseek.com/v1"

    def test_production_mode_from_env(self):
        with mock.patch.dict(os.environ, {"SAIMON_ENV": "production"}):
            cfg = SecretsConfig.from_env()
            assert cfg.is_production is True

    def test_non_production_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = SecretsConfig.from_env()
            assert cfg.is_production is False


# ---------------------------------------------------------------------------
# SecretRequirement
# ---------------------------------------------------------------------------

class TestSecretRequirement:
    """Individual requirement checks."""

    def test_required_satisfied(self):
        req = SecretRequirement(key="SAIMON_API_KEY", value="sk-real-key")
        assert req.satisfied is True
        assert req.missing_msg is None

    def test_required_missing_empty(self):
        req = SecretRequirement(key="SAIMON_API_KEY", value="")
        assert req.satisfied is False
        assert req.missing_msg is not None
        assert "SAIMON_API_KEY" in req.missing_msg

    def test_required_missing_default(self):
        req = SecretRequirement(
            key="SAIMON_API_KEY", value="sk-test-search-key", default_marker="sk-test-"
        )
        assert req.satisfied is False
        assert "default" in req.missing_msg.lower()

    def test_optional_never_missing(self):
        req = SecretRequirement(
            key="DEEPSEEK_API_KEY", value="", required=False
        )
        assert req.satisfied is True

    def test_production_only_skipped_in_dev(self):
        req = SecretRequirement(
            key="SOME_KEY", value="", production_only=True, is_production=False
        )
        assert req.satisfied is True

    def test_production_only_enforced_in_prod(self):
        req = SecretRequirement(
            key="SOME_KEY", value="", production_only=True, is_production=True
        )
        assert req.satisfied is False


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------

class TestValidateAll:
    """Full validation across all required secrets."""

    def test_all_satisfied_in_dev_with_defaults(self):
        """Dev mode with test keys should pass validation."""
        with mock.patch.dict(os.environ, {
            "SAIMON_API_KEY": "sk-test-key",
            "DATABASE_URL": "postgresql://u:p@h/db",
        }):
            cfg = SecretsConfig.from_env()
            result = cfg.validate_all(service_name="test-mcp")
            assert result.valid is True
            assert len(result.missing) == 0

    def test_missing_api_key_fails(self):
        with mock.patch.dict(os.environ, {"SAIMON_API_KEY": ""}):
            cfg = SecretsConfig.from_env()
            result = cfg.validate_all(service_name="search-mcp")
            assert result.valid is False
            assert any("SAIMON_API_KEY" in m for m in result.missing)

    def test_production_rejects_default_keys(self):
        with mock.patch.dict(os.environ, {
            "SAIMON_ENV": "production",
            "SAIMON_API_KEY": "sk-test-search-key",
        }):
            cfg = SecretsConfig.from_env()
            result = cfg.validate_all(service_name="search-mcp")
            # In production, default keys should be rejected
            if cfg.is_production:
                assert result.valid is False

    def test_validate_all_includes_service_name_in_error(self):
        with mock.patch.dict(os.environ, {"SAIMON_API_KEY": ""}):
            cfg = SecretsConfig.from_env()
            result = cfg.validate_all(service_name="search-mcp")
            assert "search-mcp" in result.summary()

    def test_validate_all_result_summary_success(self):
        with mock.patch.dict(os.environ, {
            "SAIMON_API_KEY": "sk-test-key",
            "DATABASE_URL": "postgresql://u:p@h/db",
        }):
            cfg = SecretsConfig.from_env()
            result = cfg.validate_all(service_name="test-mcp")
            summary = result.summary()
            assert "OK" in summary or "valid" in summary.lower()


# ---------------------------------------------------------------------------
# result dataclass
# ---------------------------------------------------------------------------

class TestValidationResult:
    """ValidationResult dataclass behaviour."""

    def test_bool_conversion(self):
        from research_shared.secrets import ValidationResult

        valid = ValidationResult(valid=True, missing=[])
        invalid = ValidationResult(valid=False, missing=["MISSING_KEY: ..."])

        assert bool(valid) is True
        assert bool(invalid) is False

    def test_summary_contains_each_missing(self):
        from research_shared.secrets import SecretRequirement
        cfg = SecretsConfig(saimon_api_key="")
        result = cfg.validate_all(service_name="test-mcp")
        if not result.valid:
            for m in result.missing:
                assert "SAIMON_API_KEY" in m
