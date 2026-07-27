"""Tests for research_shared.auth — API key validation, fail-closed auth."""

import pytest

from research_shared.auth import AuthConfig, AuthError, AuthValidator


class TestAuthConfig:
    def test_from_env_defaults(self, clean_env):
        """With no env vars, uses sensible defaults."""
        config = AuthConfig.from_env()
        assert config.api_key is None
        assert config.header_name == "X-Saimon-API-Key"

    def test_from_env_reads_api_key(self, mock_api_key_env):
        """Reads SAIMON_API_KEY from environment."""
        config = AuthConfig.from_env()
        assert config.api_key == "sk-test-mock-key-12345"

    def test_from_env_custom_header(self, clean_env, monkeypatch):
        """Custom header name env var is respected."""
        monkeypatch.setenv("SAIMON_AUTH_HEADER", "X-Custom-Key")
        config = AuthConfig.from_env()
        assert config.header_name == "X-Custom-Key"


class TestAuthError:
    def test_auth_error_is_exception(self):
        """AuthError is a proper exception class."""
        err = AuthError("Invalid API key")
        assert str(err) == "Invalid API key"
        assert isinstance(err, Exception)


class TestAuthValidator:
    def test_no_api_key_configured_fails_closed(self, clean_env):
        """Fail-closed: validator without API key rejects all requests."""
        config = AuthConfig(api_key=None)
        validator = AuthValidator(config)
        assert validator.has_api_key is False

    def test_validator_with_api_key(self, mock_api_key_env):
        """Validator with an API key is active."""
        config = AuthConfig(api_key="sk-test-key")
        validator = AuthValidator(config)
        assert validator.has_api_key is True

    def test_validate_correct_key(self):
        """Correct API key passes validation."""
        config = AuthConfig(api_key="sk-secret")
        validator = AuthValidator(config)
        # Should not raise
        validator.validate("sk-secret")

    def test_validate_incorrect_key_raises(self):
        """Wrong API key raises AuthError."""
        config = AuthConfig(api_key="sk-secret")
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Invalid API key"):
            validator.validate("sk-wrong")

    def test_validate_missing_key_raises(self):
        """Missing API key raises AuthError."""
        config = AuthConfig(api_key="sk-secret")
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Missing API key"):
            validator.validate(None)

    def test_validate_empty_key_raises(self):
        """Empty API key raises AuthError."""
        config = AuthConfig(api_key="sk-secret")
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Missing API key"):
            validator.validate("")

    def test_extract_from_headers(self):
        """Extracts API key from request headers."""
        config = AuthConfig(api_key="sk-secret", header_name="X-API-Key")
        validator = AuthValidator(config)
        key = validator.extract_from_headers({"X-API-Key": "sk-secret"})
        assert key == "sk-secret"

    def test_extract_missing_header(self):
        """Returns None when header is absent."""
        config = AuthConfig(api_key="sk-secret")
        validator = AuthValidator(config)
        key = validator.extract_from_headers({})
        assert key is None
