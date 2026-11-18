"""A missing production secret must stop the service, not weaken it."""

from __future__ import annotations

import pytest

from research_shared.config_guard import DEV_SECRET, resolve_jwt_secret


def _env(values: dict[str, str]):
    return lambda name, default="": values.get(name, default)


def test_production_without_secret_refuses_to_start() -> None:
    with pytest.raises(RuntimeError, match="SAIMON_JWT_SECRET"):
        resolve_jwt_secret(env="production", getenv=_env({}))


def test_production_with_the_published_default_refuses() -> None:
    with pytest.raises(RuntimeError):
        resolve_jwt_secret(
            env="production", getenv=_env({"SAIMON_JWT_SECRET": DEV_SECRET}))


def test_development_without_secret_keeps_the_dev_value() -> None:
    assert resolve_jwt_secret(env="development", getenv=_env({})) == DEV_SECRET
    assert resolve_jwt_secret(env="", getenv=_env({})) == DEV_SECRET


def test_production_with_a_real_secret_is_accepted() -> None:
    secret = "s" * 48
    assert resolve_jwt_secret(
        env="production", getenv=_env({"SAIMON_JWT_SECRET": secret})) == secret


def test_a_short_secret_warns_but_is_not_rejected() -> None:
    # Rotation invalidates live sessions, so this is an operator decision: the
    # service starts and says how short the key is.
    secret = "short-secret-value"
    assert resolve_jwt_secret(
        env="production", getenv=_env({"SAIMON_JWT_SECRET": secret})) == secret
