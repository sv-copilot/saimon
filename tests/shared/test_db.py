"""Tests for research_shared.db — PostgreSQL connection pool wrapper."""

import pytest
from research_shared.db import DatabaseConfig, DatabaseError


class TestDatabaseConfig:
    def test_from_env_defaults(self, clean_env):
        """With no env vars, uses sensible defaults."""
        config = DatabaseConfig.from_env()
        assert config.database_url is None
        assert config.min_pool_size == 2
        assert config.max_pool_size == 10

    def test_from_env_reads_url(self, mock_db_url_env):
        """Reads SAIMON_DATABASE_URL from environment."""
        config = DatabaseConfig.from_env()
        assert config.database_url == (
            "postgresql://user:pass@localhost:5432/saimon_test"
        )

    def test_from_env_custom_pool(self, clean_env, monkeypatch):
        """Custom pool size env vars are respected."""
        monkeypatch.setenv("SAIMON_DB_MIN_POOL", "3")
        monkeypatch.setenv("SAIMON_DB_MAX_POOL", "20")
        config = DatabaseConfig.from_env()
        assert config.min_pool_size == 3
        assert config.max_pool_size == 20

    def test_repr_masks_password(self):
        """Config repr hides the password in the URL."""
        config = DatabaseConfig(
            database_url="postgresql://user:secret@localhost/db"
        )
        r = repr(config)
        assert "secret" not in r


class TestDatabaseError:
    def test_database_error_is_exception(self):
        """DatabaseError is a proper exception class."""
        err = DatabaseError("Connection refused")
        assert str(err) == "Connection refused"
        assert isinstance(err, Exception)


class TestDatabasePool:
    def test_pool_requires_url(self, clean_env):
        """Fail-closed: constructing pool without a URL raises."""
        from research_shared.db import DatabasePool

        config = DatabaseConfig(database_url=None)
        with pytest.raises(DatabaseError, match="database URL"):
            DatabasePool(config)

    def test_pool_interface_exists(self, mock_db_url_env):
        """Pool exposes the expected async interface methods."""
        from research_shared.db import DatabasePool

        config = DatabaseConfig(
            database_url="postgresql://user:pass@localhost/db"
        )
        pool = DatabasePool(config)

        for method in ("execute", "fetch", "fetchrow", "fetchval", "close"):
            assert hasattr(pool, method), f"Pool missing method: {method}"
