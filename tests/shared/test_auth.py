"""Tests for research_shared.auth — API key validation, multi-key support, key rotation."""

import time

import pytest

from research_shared.auth import AuthConfig, AuthError, AuthValidator, hash_key


class TestAuthConfig:
    def test_from_env_defaults(self, clean_env):
        """With no env vars, uses sensible defaults."""
        config = AuthConfig.from_env()
        assert config.api_keys == set()
        assert config.old_api_keys == set()
        assert config.header_name == "X-Saimon-API-Key"

    def test_from_env_reads_api_key(self, mock_api_key_env):
        """Reads SAIMON_API_KEY from environment."""
        config = AuthConfig.from_env()
        assert "sk-test-mock-key-12345" in config.api_keys

    def test_from_env_multiple_keys(self, clean_env, monkeypatch):
        """Supports comma-separated multiple API keys."""
        monkeypatch.setenv("SAIMON_API_KEY", "key1, key2 , key3")
        config = AuthConfig.from_env()
        assert config.api_keys == {"key1", "key2", "key3"}

    def test_from_env_old_keys(self, clean_env, monkeypatch):
        """Reads SAIMON_API_KEY_OLD for rotation."""
        monkeypatch.setenv("SAIMON_API_KEY", "new-key")
        monkeypatch.setenv("SAIMON_API_KEY_OLD", "old-key")
        config = AuthConfig.from_env()
        assert "new-key" in config.api_keys
        assert "old-key" in config.old_api_keys

    def test_from_env_custom_header(self, clean_env, monkeypatch):
        """Custom header name env var is respected."""
        monkeypatch.setenv("SAIMON_AUTH_HEADER", "X-Custom-Key")
        config = AuthConfig.from_env()
        assert config.header_name == "X-Custom-Key"

    def test_from_env_rotation_overlap(self, clean_env, monkeypatch):
        """Custom rotation overlap is read from env."""
        monkeypatch.setenv("SAIMON_KEY_ROTATION_OVERLAP", "7200")
        config = AuthConfig.from_env()
        assert config.rotation_overlap_seconds == 7200


class TestHashKey:
    def test_hash_key_deterministic(self):
        """Same key always produces same hash."""
        assert hash_key("test-key") == hash_key("test-key")

    def test_hash_key_different_keys(self):
        """Different keys produce different hashes."""
        assert hash_key("key-a") != hash_key("key-b")

    def test_hash_key_length(self):
        """Hash is 8 hex characters."""
        assert len(hash_key("any-key")) == 8


class TestAuthError:
    def test_auth_error_is_exception(self):
        """AuthError is a proper exception class."""
        err = AuthError("Invalid API key")
        assert str(err) == "Invalid API key"
        assert isinstance(err, Exception)


class TestAuthValidator:
    def test_no_api_key_configured_fails_closed(self, clean_env):
        """Fail-closed: validator without API key rejects all requests."""
        config = AuthConfig(api_keys=set())
        validator = AuthValidator(config)
        assert validator.has_api_key is False

    def test_validator_with_api_key(self):
        """Validator with an API key is active."""
        config = AuthConfig(api_keys={"sk-test-key"})
        validator = AuthValidator(config)
        assert validator.has_api_key is True

    def test_validate_correct_key(self):
        """Correct API key passes validation."""
        config = AuthConfig(api_keys={"sk-secret"})
        validator = AuthValidator(config)
        result = validator.validate("sk-secret")
        assert result == "sk-secret"

    def test_validate_incorrect_key_raises(self):
        """Wrong API key raises AuthError."""
        config = AuthConfig(api_keys={"sk-secret"})
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Invalid API key"):
            validator.validate("sk-wrong")

    def test_validate_missing_key_raises(self):
        """Missing API key raises AuthError."""
        config = AuthConfig(api_keys={"sk-secret"})
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Missing API key"):
            validator.validate(None)

    def test_validate_empty_key_raises(self):
        """Empty API key raises AuthError."""
        config = AuthConfig(api_keys={"sk-secret"})
        validator = AuthValidator(config)
        with pytest.raises(AuthError, match="Missing API key"):
            validator.validate("")

    def test_extract_from_headers(self):
        """Extracts API key from request headers."""
        config = AuthConfig(api_keys={"sk-secret"}, header_name="X-API-Key")
        validator = AuthValidator(config)
        key = validator.extract_from_headers({"X-API-Key": "sk-secret"})
        assert key == "sk-secret"

    def test_extract_missing_header(self):
        """Returns None when header is absent."""
        config = AuthConfig(api_keys={"sk-secret"})
        validator = AuthValidator(config)
        key = validator.extract_from_headers({})
        assert key is None

    # ── multi-key tests ──────────────────────────────────────────

    def test_validate_any_of_multiple_keys(self):
        """Any of the configured keys passes validation."""
        config = AuthConfig(api_keys={"key-a", "key-b", "key-c"})
        validator = AuthValidator(config)
        assert validator.active_key_count == 3
        validator.validate("key-a")  # should not raise
        validator.validate("key-b")
        validator.validate("key-c")

    def test_validate_wrong_key_with_multiple(self):
        """Wrong key still fails even with multiple valid keys."""
        config = AuthConfig(api_keys={"key-a", "key-b"})
        validator = AuthValidator(config)
        with pytest.raises(AuthError):
            validator.validate("key-wrong")

    # ── key rotation tests ───────────────────────────────────────

    def test_old_key_valid_during_rotation(self):
        """Old key is accepted during overlap period."""
        config = AuthConfig(
            api_keys={"new-key"},
            old_api_keys={"old-key"},
            rotation_overlap_seconds=3600,
        )
        validator = AuthValidator(config)
        assert validator.active_key_count == 2
        result = validator.validate("old-key")
        assert result == "old-key"

    def test_new_key_valid_during_rotation(self):
        """New key is accepted during overlap period."""
        config = AuthConfig(
            api_keys={"new-key"},
            old_api_keys={"old-key"},
            rotation_overlap_seconds=3600,
        )
        validator = AuthValidator(config)
        result = validator.validate("new-key")
        assert result == "new-key"

    def test_old_key_expires_after_overlap(self):
        """Old key is rejected after overlap period."""
        config = AuthConfig(
            api_keys={"new-key"},
            old_api_keys={"old-key"},
            rotation_overlap_seconds=0,  # immediate expiry
        )
        validator = AuthValidator(config)
        # Force overlap check
        time.sleep(0.01)
        with pytest.raises(AuthError, match="Invalid API key"):
            validator.validate("old-key")

    def test_no_old_keys_no_rotation(self):
        """Without old keys, only new keys are valid."""
        config = AuthConfig(api_keys={"only-key"})
        validator = AuthValidator(config)
        assert validator.active_key_count == 1

    # ── hash_for_audit tests ─────────────────────────────────────

    def test_hash_for_audit(self):
        """Returns a hashed key for audit."""
        config = AuthConfig(api_keys={"sk-test"})
        validator = AuthValidator(config)
        h = validator.hash_for_audit("sk-test")
        assert len(h) == 8
        assert h == hash_key("sk-test")

    def test_hash_for_audit_none(self):
        """Returns 'anonymous' for None key."""
        config = AuthConfig(api_keys={"sk-test"})
        validator = AuthValidator(config)
        assert validator.hash_for_audit(None) == "anonymous"

    def test_hash_for_audit_empty(self):
        """Returns 'anonymous' for empty string."""
        config = AuthConfig(api_keys={"sk-test"})
        validator = AuthValidator(config)
        h = validator.hash_for_audit("")
        assert h == "anonymous"
