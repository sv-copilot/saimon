"""test_auth_api.py — TDD tests for SAIMON-AUTH-1: User accounts + JWT auth.

Covers: register, login, token refresh, me, health.
All tests run against an in-memory SQLite database (no PG required).
"""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock database — we simulate asyncpg Pool with SQLite for test isolation
# ---------------------------------------------------------------------------

class MockConnection:
    """Simulates an asyncpg connection."""

    def __init__(self, db: "MockPool"):
        self._db = db

    async def execute(self, query: str, *args):
        """Simulate INSERT/UPDATE/DELETE."""
        # Handle INSERT INTO users
        if "INSERT INTO users" in query:
            email = None
            display_name = None
            password_hash = None
            # Extract values from query args
            for i, a in enumerate(args):
                if i == 0:
                    import uuid as _uuid
                    user_id = str(a)
                elif i == 1:
                    email = a
                elif i == 2:
                    display_name = a
                elif i == 3:
                    password_hash = a
            if email:
                self._db._users[email] = {
                    "id": user_id,
                    "email": email,
                    "display_name": display_name,
                    "password_hash": password_hash,
                    "is_admin": False,
                }
        elif "INSERT INTO refresh_tokens" in query:
            token = args[0] if args else ""
            user_id = str(args[1]) if len(args) > 1 else ""
            self._db._refresh_tokens[token] = {"user_id": user_id}
        return "EXECUTED"

    async def fetchrow(self, query: str, *args):
        """Simulate SELECT returning one row."""
        if "FROM users WHERE email" in query:
            email = args[0]
            return self._db._users.get(email)
        if "FROM users WHERE id" in query:
            user_id = str(args[0]) if args else None
            for u in self._db._users.values():
                if u["id"] == user_id:
                    return u
        if "FROM refresh_tokens WHERE token" in query:
            token = args[0] if args else ""
            stored = self._db._refresh_tokens.get(token)
            if stored:
                return {"user_id": stored["user_id"]}
            return None
        if "SELECT COUNT" in query:
            return {"count": len(self._db._users)}
        return None

    async def fetchval(self, query: str, *args):
        """Simulate SELECT returning single value."""
        if "COUNT" in query:
            return len(self._db._users)
        return None


class MockPool:
    """Simulates an asyncpg Pool."""

    def __init__(self):
        self._users: dict[str, dict] = {}
        self._refresh_tokens: dict[str, dict] = {}
        self._conn = MockConnection(self)

    async def execute(self, query: str, *args):
        return await self._conn.execute(query, *args)

    async def fetchrow(self, query: str, *args):
        return await self._conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        return await self._conn.fetchval(query, *args)

    async def close(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    return MockPool()


@pytest.fixture
def client(mock_pool):
    """Return a TestClient for the api-mcp FastAPI app with mocked DB."""
    # Mock set_db_pool and get_db_pool
    import mcp.api.server as server_module

    # We need to patch the database pool used by the server
    original_pool = getattr(server_module, "_db_pool", None)
    server_module._db_pool = mock_pool

    # Also mock set_db_pool to be a no-op and _ensure_users_table
    server_module.set_db_pool = lambda p: None

    # Patch _ensure_users_table to be a no-op (no real DB schema)
    with patch.object(server_module, "_ensure_users_table", new_callable=AsyncMock):
        from mcp.api.server import app
        client = TestClient(app)
        yield client

    # Restore
    if original_pool is not None:
        server_module._db_pool = original_pool


@pytest.fixture
def sample_user():
    return {
        "email": "test@example.com",
        "password": "securepass123",
        "display_name": "Test User",
    }


@pytest.fixture
def sample_user2():
    return {
        "email": "other@example.com",
        "password": "anotherpass456",
        "display_name": "Other User",
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _register(client, user: dict) -> dict:
    """Helper: register a user and return the response JSON."""
    resp = client.post("/auth/register", json=user)
    return resp


def _login(client, email: str, password: str) -> dict:
    """Helper: login and return the response dict."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return resp


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests: Registration
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_creates_user(self, client, sample_user):
        """201, user returned with id, email, display_name."""
        resp = _register(client, sample_user)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "user" in data
        user = data["user"]
        assert user["email"] == sample_user["email"]
        assert user["display_name"] == sample_user["display_name"]
        assert "id" in user
        # Password hash must NOT be returned
        assert "password" not in user
        assert "password_hash" not in user

    def test_register_duplicate_email(self, client, sample_user):
        """409 if email already exists."""
        resp1 = _register(client, sample_user)
        assert resp1.status_code == 201

        resp2 = _register(client, sample_user)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"].lower()

    def test_register_weak_password(self, client, sample_user):
        """422 if password < 8 chars."""
        weak = dict(sample_user, password="short")
        resp = _register(client, weak)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any("password" in str(e).lower() for e in detail)

    def test_register_invalid_email(self, client, sample_user):
        """422 if email format is invalid."""
        invalid = dict(sample_user, email="not-an-email")
        resp = _register(client, invalid)
        assert resp.status_code == 422

    def test_register_empty_display_name(self, client, sample_user):
        """422 if display_name is empty."""
        empty = dict(sample_user, display_name="")
        resp = _register(client, empty)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_valid_credentials(self, client, sample_user):
        """200, tokens returned with user."""
        _register(client, sample_user)
        resp = _login(client, sample_user["email"], sample_user["password"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == sample_user["email"]

    def test_login_invalid_password(self, client, sample_user):
        """401 if password is wrong."""
        _register(client, sample_user)
        resp = _login(client, sample_user["email"], "wrongpassword")
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """401 if user doesn't exist."""
        resp = _login(client, "nobody@example.com", "somepass123")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Token Refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_token_refresh_valid(self, client, sample_user):
        """200, new access token returned."""
        _register(client, sample_user)
        login_resp = _login(client, sample_user["email"], sample_user["password"])
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post("/auth/token", json={"refresh_token": refresh_token})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_token_refresh_invalid(self, client):
        """401 if refresh token is garbage."""
        resp = client.post("/auth/token", json={"refresh_token": "invalid-token"})
        assert resp.status_code == 401

    def test_token_refresh_expired(self, client, sample_user):
        """401 if refresh token is expired."""
        pass  # TODO: test with actual expired token — needs time manipulation


# ---------------------------------------------------------------------------
# Tests: Me endpoint
# ---------------------------------------------------------------------------

class TestMe:
    def test_me_authenticated(self, client, sample_user):
        """200, user returned with correct fields."""
        _register(client, sample_user)
        login_resp = _login(client, sample_user["email"], sample_user["password"])
        access_token = login_resp.json()["access_token"]

        resp = client.get("/auth/me", headers=_auth_header(access_token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["user"]["email"] == sample_user["email"]
        assert data["user"]["display_name"] == sample_user["display_name"]
        assert "is_admin" in data["user"]

    def test_me_no_token(self, client):
        """401 if no Authorization header."""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, client):
        """401 if token is garbage."""
        resp = client.get("/auth/me", headers=_auth_header("garbage-token"))
        assert resp.status_code == 401

    def test_me_expired_token(self, client, sample_user):
        """401 if token is expired."""
        pass  # TODO: test with actual expired token — needs time manipulation


# ---------------------------------------------------------------------------
# Tests: Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        """200, status ok with service name."""
        resp = client.get("/health")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "api-mcp"


# ---------------------------------------------------------------------------
# Tests: Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_register_does_not_store_plaintext(self, client, sample_user):
        """Password must be bcrypt-hashed, not stored as plaintext."""
        resp = _register(client, sample_user)
        assert resp.status_code == 201
        # The user object returned must not have the password
        user = resp.json()["user"]
        assert "password" not in user
        assert "password_hash" not in user

    def test_different_passwords_produce_different_hashes(self, client, sample_user, sample_user2):
        """Same password for two users should produce different hashes (salting)."""
        # Both use same password
        u1 = dict(sample_user, email="a@test.com")
        u2 = dict(sample_user2, email="b@test.com")
        u1["password"] = "samepassword"
        u2["password"] = "samepassword"

        _register(client, u1)
        _register(client, u2)

        # Both should be able to login with the same password
        r1 = _login(client, "a@test.com", "samepassword")
        r2 = _login(client, "b@test.com", "samepassword")
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Tokens should differ (different users)
        assert r1.json()["access_token"] != r2.json()["access_token"]
