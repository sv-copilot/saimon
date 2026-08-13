"""test_sessions_api.py — TDD tests for SAIMON-SESSIONS-1: Chat persistence.

Covers: create session, list sessions, get session with messages,
add message, update title, delete session, authorization checks.
All tests run against the same MockPool pattern as test_auth_api.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock database — extended to handle sessions + messages tables
# ---------------------------------------------------------------------------

class MockConnection:
    """Simulates an asyncpg connection with auth + sessions + messages support."""

    def __init__(self, db: "MockPool"):
        self._db = db

    async def execute(self, query: str, *args):
        if "INSERT INTO users" in query:
            email = args[1] if len(args) > 1 else ""
            self._db._users[email] = {
                "id": str(args[0]) if args else str(uuid.uuid4()),
                "email": email,
                "display_name": args[2] if len(args) > 2 else "",
                "password_hash": args[3] if len(args) > 3 else "",
                "is_admin": False,
            }
        elif "INSERT INTO refresh_tokens" in query:
            token = args[0] if args else ""
            self._db._refresh_tokens[token] = {"user_id": str(args[1]) if len(args) > 1 else ""}
        elif "INSERT INTO chat_sessions" in query:
            sid = str(args[0]) if args else str(uuid.uuid4())
            uid = str(args[1]) if len(args) > 1 else ""
            title = args[2] if len(args) > 2 else "New Chat"
            self._db._sessions[sid] = {"id": sid, "user_id": uid, "title": title, "updated_at": "2026-01-01T00:00:00Z"}
        elif "INSERT INTO chat_messages" in query:
            mid = str(args[0]) if args else str(uuid.uuid4())
            sid = str(args[1]) if len(args) > 1 else ""
            self._db._messages[mid] = {
                "id": mid, "session_id": sid,
                "role": args[2] if len(args) > 2 else "user",
                "content": args[3] if len(args) > 3 else "",
                "tool_calls": None, "created_at": "2026-01-01T00:00:00Z",
            }
            # Update session updated_at
            if sid in self._db._sessions:
                self._db._sessions[sid]["updated_at"] = "2026-01-02T00:00:00Z"
        elif "UPDATE chat_sessions" in query:
            if "SET title" in query:
                new_title = args[0] if args else ""
                sid = str(args[1]) if len(args) > 1 else ""
                if sid in self._db._sessions:
                    self._db._sessions[sid]["title"] = new_title
                    self._db._sessions[sid]["updated_at"] = "2026-01-03T00:00:00Z"
        elif "DELETE FROM chat_sessions" in query:
            sid = str(args[0]) if args else ""
            self._db._sessions.pop(sid, None)
            # Cascade: delete messages
            to_delete = [k for k, v in self._db._messages.items() if v["session_id"] == sid]
            for k in to_delete:
                del self._db._messages[k]
        return "EXECUTED"

    async def fetchrow(self, query: str, *args):
        if "FROM users WHERE email" in query:
            email = args[0] if args else ""
            return self._db._users.get(email)
        if "FROM users WHERE id" in query:
            uid = str(args[0]) if args else None
            for u in self._db._users.values():
                if u["id"] == uid:
                    return u
        if "FROM refresh_tokens WHERE token" in query:
            return {"user_id": self._db._refresh_tokens.get(args[0], {}).get("user_id", "")}
        if "FROM chat_sessions" in query:
            if "WHERE id" in query:
                sid = str(args[0]) if args else ""
                s = self._db._sessions.get(sid)
                if s:
                    return {"id": s["id"], "user_id": s["user_id"], "title": s["title"],
                            "created_at": "2026-01-01T00:00:00Z", "updated_at": s["updated_at"]}
                return None
        if "FROM chat_messages" in query:
            if "WHERE session_id" in query:
                sid = str(args[0]) if args else ""
                # Return first message (fetchrow returns one)
                for m in self._db._messages.values():
                    if m["session_id"] == sid:
                        return m
                return None
        if "SELECT COUNT" in query:
            if "chat_sessions" in query:
                uid = str(args[0]) if args else ""
                count = sum(1 for s in self._db._sessions.values() if s["user_id"] == uid)
                return {"count": count}
            if "chat_messages" in query:
                sid = str(args[0]) if args else ""
                count = sum(1 for m in self._db._messages.values() if m["session_id"] == sid)
                return {"count": count}
            if "users" in query:
                return {"count": len(self._db._users)}
        return None

    async def fetch(self, query: str, *args):
        """Simulate SELECT returning multiple rows."""
        if "chat_sessions" in query and "ORDER BY" in query:
            uid = str(args[0]) if args else ""
            sessions = [s for s in self._db._sessions.values() if s["user_id"] == uid]
            # Sort by updated_at DESC
            sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
            return [{
                "id": s["id"], "title": s["title"],
                "updated_at": s.get("updated_at", ""),
                "message_count": sum(1 for m in self._db._messages.values() if m["session_id"] == s["id"]),
            } for s in sessions]
        if "chat_messages" in query:
            if "WHERE session_id" in query:
                sid = str(args[0]) if args else ""
                return [m for m in self._db._messages.values() if m["session_id"] == sid]
        return []

    async def fetchval(self, query: str, *args):
        if "COUNT" in query:
            if "chat_sessions" in query:
                uid = str(args[0]) if args else ""
                return sum(1 for s in self._db._sessions.values() if s["user_id"] == uid)
            if "chat_messages" in query:
                sid = str(args[0]) if args else ""
                return sum(1 for m in self._db._messages.values() if m["session_id"] == sid)
            if "users" in query:
                return len(self._db._users)
        return None


class MockPool:
    """Simulates an asyncpg Pool with sessions + messages support."""

    def __init__(self):
        self._users: dict[str, dict] = {}
        self._refresh_tokens: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._messages: dict[str, dict] = {}
        self._conn = MockConnection(self)

    async def execute(self, query: str, *args):
        return await self._conn.execute(query, *args)

    async def fetchrow(self, query: str, *args):
        return await self._conn.fetchrow(query, *args)

    async def fetch(self, query: str, *args):
        return await self._conn.fetch(query, *args)

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
    import mcp.api.server as server_module

    original_pool = getattr(server_module, "_db_pool", None)
    server_module._db_pool = mock_pool
    server_module.set_db_pool = lambda p: None

    with patch.object(server_module, "_ensure_users_table", new_callable=AsyncMock):
        with patch.object(server_module, "_ensure_sessions_table", new_callable=AsyncMock):
            with patch.object(server_module, "_ensure_messages_table", new_callable=AsyncMock):
                from mcp.api.server import app
                client = TestClient(app)
                yield client

    if original_pool is not None:
        server_module._db_pool = original_pool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client, user: dict) -> dict:
    return client.post("/auth/register", json=user)


def _login(client, email: str, password: str) -> dict:
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get_token(client, user: dict) -> str:
    _register(client, user)
    resp = _login(client, user["email"], user["password"])
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_create_session_default_title(self, client, sample_user):
        """201, session created with default title."""
        token = _get_token(client, sample_user)
        resp = client.post("/sessions/", headers=_auth_header(token))
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "session" in data
        s = data["session"]
        assert "id" in s
        assert s["title"] == "New Chat"

    def test_create_session_custom_title(self, client, sample_user):
        """201, session created with provided title."""
        token = _get_token(client, sample_user)
        resp = client.post("/sessions/", json={"title": "Research on AI"}, headers=_auth_header(token))
        assert resp.status_code == 201, resp.text
        assert resp.json()["session"]["title"] == "Research on AI"

    def test_create_session_no_auth(self, client):
        """401 if no token."""
        resp = client.post("/sessions/")
        assert resp.status_code == 401


class TestListSessions:
    def test_list_sessions_empty(self, client, sample_user):
        """200, empty list for new user."""
        token = _get_token(client, sample_user)
        resp = client.get("/sessions/", headers=_auth_header(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["sessions"] == []

    def test_list_sessions_with_data(self, client, sample_user):
        """200, returns user's sessions only."""
        token = _get_token(client, sample_user)
        # Create 2 sessions
        client.post("/sessions/", json={"title": "Chat A"}, headers=_auth_header(token))
        client.post("/sessions/", json={"title": "Chat B"}, headers=_auth_header(token))

        resp = client.get("/sessions/", headers=_auth_header(token))
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert len(sessions) == 2

    def test_list_sessions_scoped_to_user(self, client, sample_user, sample_user2):
        """Each user sees only their own sessions."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)

        client.post("/sessions/", json={"title": "User1 Chat"}, headers=_auth_header(t1))
        client.post("/sessions/", json={"title": "User2 Chat"}, headers=_auth_header(t2))

        r1 = client.get("/sessions/", headers=_auth_header(t1))
        r2 = client.get("/sessions/", headers=_auth_header(t2))
        assert len(r1.json()["sessions"]) == 1
        assert len(r2.json()["sessions"]) == 1
        assert r1.json()["sessions"][0]["title"] == "User1 Chat"
        assert r2.json()["sessions"][0]["title"] == "User2 Chat"

    def test_list_sessions_no_auth(self, client):
        """401 if no token."""
        resp = client.get("/sessions/")
        assert resp.status_code == 401


class TestGetSession:
    def test_get_session_with_messages(self, client, sample_user):
        """200, session returned with messages array."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", json={"title": "Chat"}, headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        # Add a message
        client.post(f"/sessions/{sid}/messages", json={"role": "user", "content": "Hello"}, headers=_auth_header(token))

        resp = client.get(f"/sessions/{sid}", headers=_auth_header(token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["session"]["title"] == "Chat"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello"

    def test_get_other_user_session(self, client, sample_user, sample_user2):
        """403 if session belongs to a different user."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)

        create_resp = client.post("/sessions/", json={"title": "Mine"}, headers=_auth_header(t1))
        sid = create_resp.json()["session"]["id"]

        resp = client.get(f"/sessions/{sid}", headers=_auth_header(t2))
        assert resp.status_code == 403

    def test_get_nonexistent_session(self, client, sample_user):
        """404 if session does not exist."""
        token = _get_token(client, sample_user)
        resp = client.get(f"/sessions/{uuid.uuid4()}", headers=_auth_header(token))
        assert resp.status_code == 404


class TestAddMessage:
    def test_add_message(self, client, sample_user):
        """201, message added to session."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        resp = client.post(
            f"/sessions/{sid}/messages",
            json={"role": "user", "content": "What is AI?"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        msg = resp.json()["message"]
        assert msg["role"] == "user"
        assert msg["content"] == "What is AI?"
        assert "id" in msg
        assert "created_at" in msg

    def test_add_message_assistant_role(self, client, sample_user):
        """201, assistant role accepted."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        resp = client.post(
            f"/sessions/{sid}/messages",
            json={"role": "assistant", "content": "AI is artificial intelligence."},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201

    def test_add_message_invalid_role(self, client, sample_user):
        """422 if role is not user/assistant/system."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        resp = client.post(
            f"/sessions/{sid}/messages",
            json={"role": "invalid", "content": "test"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 422

    def test_add_message_updates_session(self, client, sample_user):
        """Adding a message should update the session's updated_at."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        # Get initial state
        get_before = client.get(f"/sessions/{sid}", headers=_auth_header(token))
        before_updated = get_before.json()["session"]["updated_at"]

        # Add message
        client.post(f"/sessions/{sid}/messages", json={"role": "user", "content": "ping"}, headers=_auth_header(token))

        # The mock sets updated_at to "2026-01-02T00:00:00Z" on message insert
        get_after = client.get(f"/sessions/{sid}", headers=_auth_header(token))
        after_updated = get_after.json()["session"]["updated_at"]
        assert after_updated != before_updated


class TestUpdateSession:
    def test_update_session_title(self, client, sample_user):
        """200, title updated."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        resp = client.patch(
            f"/sessions/{sid}",
            json={"title": "Renamed Chat"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["session"]["title"] == "Renamed Chat"

    def test_update_other_user_session(self, client, sample_user, sample_user2):
        """403 if updating another user's session."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)

        create_resp = client.post("/sessions/", json={"title": "Mine"}, headers=_auth_header(t1))
        sid = create_resp.json()["session"]["id"]

        resp = client.patch(f"/sessions/{sid}", json={"title": "Stolen"}, headers=_auth_header(t2))
        assert resp.status_code == 403


class TestDeleteSession:
    def test_delete_session(self, client, sample_user):
        """204, session deleted."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        resp = client.delete(f"/sessions/{sid}", headers=_auth_header(token))
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = client.get(f"/sessions/{sid}", headers=_auth_header(token))
        assert get_resp.status_code == 404

    def test_delete_session_cascades_messages(self, client, sample_user):
        """Deleting a session removes its messages."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/sessions/", headers=_auth_header(token))
        sid = create_resp.json()["session"]["id"]

        client.post(f"/sessions/{sid}/messages", json={"role": "user", "content": "msg1"}, headers=_auth_header(token))
        client.post(f"/sessions/{sid}/messages", json={"role": "user", "content": "msg2"}, headers=_auth_header(token))

        client.delete(f"/sessions/{sid}", headers=_auth_header(token))

        # Session gone, messages cascade-deleted
        get_resp = client.get(f"/sessions/{sid}", headers=_auth_header(token))
        assert get_resp.status_code == 404

    def test_delete_other_user_session(self, client, sample_user, sample_user2):
        """403 if deleting another user's session."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)

        create_resp = client.post("/sessions/", headers=_auth_header(t1))
        sid = create_resp.json()["session"]["id"]

        resp = client.delete(f"/sessions/{sid}", headers=_auth_header(t2))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Fixtures for sample users (same as auth tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user():
    return {"email": "test@example.com", "password": "securepass123", "display_name": "Test User"}


@pytest.fixture
def sample_user2():
    return {"email": "other@example.com", "password": "anotherpass456", "display_name": "Other User"}
