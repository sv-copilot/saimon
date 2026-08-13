"""test_documents_api.py — TDD tests for SAIMON-DOCUMENTS-1: Document storage.

Covers: create, list, filter, get, update, delete, authorization checks.
All tests run against the same MockPool pattern as test_auth_api.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock database — extended for auth + sessions + messages + documents
# ---------------------------------------------------------------------------

class MockConnection:
    """Simulates an asyncpg connection with auth + sessions + messages + documents."""

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
            self._db._refresh_tokens[args[0]] = {"user_id": str(args[1]) if len(args) > 1 else ""}
        elif "INSERT INTO chat_sessions" in query:
            sid = str(args[0])
            self._db._sessions[sid] = {"id": sid, "user_id": str(args[1]), "title": args[2] if len(args) > 2 else "New Chat", "updated_at": "2026-01-01T00:00:00Z"}
        elif "INSERT INTO chat_messages" in query:
            mid = str(args[0])
            self._db._messages[mid] = {"id": mid, "session_id": str(args[1]), "role": args[2] if len(args) > 2 else "user", "content": args[3] if len(args) > 3 else "", "tool_calls": None, "created_at": "2026-01-01T00:00:00Z"}
        elif "INSERT INTO documents" in query:
            did = str(args[0])
            uid = str(args[1]) if len(args) > 1 else ""
            sid = str(args[2]) if len(args) > 2 and args[2] is not None else None
            title = args[3] if len(args) > 3 else "Untitled"
            content = args[4] if len(args) > 4 else ""
            content_type = args[5] if len(args) > 5 else None
            is_published = args[6] if len(args) > 6 else False
            self._db._documents[did] = {
                "id": did, "user_id": uid, "session_id": sid,
                "title": title, "content": content, "content_type": content_type,
                "metadata": None, "is_published": is_published,
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            }
        elif "UPDATE documents" in query:
            did = str(args[-1])  # last arg is the doc id
            if did in self._db._documents:
                # args[:-1] are the SET values in order (title, content, metadata...)
                set_args = args[:-1]
                for i, a in enumerate(set_args):
                    if i == 0 and a is not None:
                        self._db._documents[did]["title"] = a
                    elif i == 1 and a is not None:
                        self._db._documents[did]["content"] = a
                self._db._documents[did]["updated_at"] = "2026-01-02T00:00:00Z"
        elif "UPDATE chat_sessions" in query:
            sid = str(args[-1]) if args else ""
            if sid in self._db._sessions:
                self._db._sessions[sid]["title"] = args[0] if args else ""
                self._db._sessions[sid]["updated_at"] = "2026-01-03T00:00:00Z"
        elif "DELETE FROM chat_sessions" in query:
            sid = str(args[0]) if args else ""
            self._db._sessions.pop(sid, None)
            to_del = [k for k, v in self._db._messages.items() if v["session_id"] == sid]
            for k in to_del:
                del self._db._messages[k]
        elif "DELETE FROM documents" in query:
            did = str(args[0]) if args else ""
            self._db._documents.pop(did, None)
        return "EXECUTED"

    async def fetchrow(self, query: str, *args):
        if "FROM users WHERE email" in query:
            return self._db._users.get(args[0] if args else "")
        if "FROM users WHERE id" in query:
            uid = str(args[0]) if args else None
            for u in self._db._users.values():
                if u["id"] == uid:
                    return u
        if "FROM refresh_tokens WHERE token" in query:
            stored = self._db._refresh_tokens.get(args[0], {})
            return {"user_id": stored.get("user_id", "")} if stored else None
        if "FROM chat_sessions WHERE id" in query:
            s = self._db._sessions.get(str(args[0]) if args else "")
            if s:
                return {"id": s["id"], "user_id": s["user_id"], "title": s["title"],
                        "created_at": "2026-01-01T00:00:00Z", "updated_at": s["updated_at"]}
            return None
        if "FROM documents WHERE id" in query:
            d = self._db._documents.get(str(args[0]) if args else "")
            if d:
                return {"id": d["id"], "user_id": d["user_id"], "session_id": d.get("session_id"),
                        "title": d["title"], "content": d["content"], "content_type": d.get("content_type"),
                        "metadata": None, "is_published": d.get("is_published", False),
                        "created_at": d["created_at"], "updated_at": d["updated_at"]}
            return None
        if "FROM documents" in query and "WHERE user_id" in query and "AND content_type" in query:
            # Filter by content_type
            uid = str(args[0]) if args else ""
            ct = str(args[1]) if len(args) > 1 else None
            docs = [d for d in self._db._documents.values() if d["user_id"] == uid and d.get("content_type") == ct]
            # Return first as fetchrow
            return docs[0] if docs else None
        if "SELECT COUNT" in query:
            if "users" in query:
                return {"count": len(self._db._users)}
            if "chat_sessions" in query:
                uid = str(args[0]) if args else ""
                return {"count": sum(1 for s in self._db._sessions.values() if s["user_id"] == uid)}
            if "chat_messages" in query:
                sid = str(args[0]) if args else ""
                return {"count": sum(1 for m in self._db._messages.values() if m["session_id"] == sid)}
            if "documents" in query:
                if "content_type" in query:
                    uid = str(args[0]) if args else ""
                    ct = str(args[1]) if len(args) > 1 else None
                    return {"count": sum(1 for d in self._db._documents.values() if d["user_id"] == uid and d.get("content_type") == ct)}
                uid = str(args[0]) if args else ""
                return {"count": sum(1 for d in self._db._documents.values() if d["user_id"] == uid)}
        return None

    async def fetch(self, query: str, *args):
        if "chat_sessions" in query and "ORDER BY" in query:
            uid = str(args[0]) if args else ""
            sessions = [s for s in self._db._sessions.values() if s["user_id"] == uid]
            sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
            return [{"id": s["id"], "title": s["title"], "updated_at": s.get("updated_at", ""),
                     "message_count": sum(1 for m in self._db._messages.values() if m["session_id"] == s["id"])} for s in sessions]
        if "chat_messages" in query and "WHERE session_id" in query:
            sid = str(args[0]) if args else ""
            return [m for m in self._db._messages.values() if m["session_id"] == sid]
        if "FROM documents" in query and "AND content_type" in query:
            uid = str(args[0]) if args else ""
            ct = str(args[1]) if len(args) > 1 else None
            docs = [d for d in self._db._documents.values() if d["user_id"] == uid and d.get("content_type") == ct]
            docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
            return [{"id": d["id"], "title": d["title"], "content_type": d.get("content_type"),
                     "updated_at": d.get("updated_at"), "created_at": d.get("created_at"),
                     "content": d["content"], "metadata": d.get("metadata"),
                     "is_published": d.get("is_published"), "session_id": d.get("session_id"),
                     "user_id": d["user_id"]} for d in docs]
        if "FROM documents" in query and "ORDER BY" in query:
            uid = str(args[0]) if args else ""
            docs = [d for d in self._db._documents.values() if d["user_id"] == uid]
            docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
            return [{"id": d["id"], "title": d["title"], "content_type": d.get("content_type"),
                     "updated_at": d.get("updated_at"), "created_at": d.get("created_at"),
                     "content": d["content"], "metadata": d.get("metadata"),
                     "is_published": d.get("is_published"), "session_id": d.get("session_id"),
                     "user_id": d["user_id"]} for d in docs]
        return []

    async def fetchval(self, query: str, *args):
        if "COUNT" in query:
            if "documents" in query:
                if "content_type" in query:
                    uid = str(args[0]) if args else ""
                    ct = str(args[1]) if len(args) > 1 else None
                    return sum(1 for d in self._db._documents.values() if d["user_id"] == uid and d.get("content_type") == ct)
                uid = str(args[0]) if args else ""
                return sum(1 for d in self._db._documents.values() if d["user_id"] == uid)
            if "users" in query:
                return len(self._db._users)
            if "chat_sessions" in query:
                uid = str(args[0]) if args else ""
                return sum(1 for s in self._db._sessions.values() if s["user_id"] == uid)
            if "chat_messages" in query:
                sid = str(args[0]) if args else ""
                return sum(1 for m in self._db._messages.values() if m["session_id"] == sid)
        return None


class MockPool:
    """Simulates an asyncpg Pool with full table support."""

    def __init__(self):
        self._users: dict[str, dict] = {}
        self._refresh_tokens: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._messages: dict[str, dict] = {}
        self._documents: dict[str, dict] = {}
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
    """Return a TestClient with all table ensure functions mocked."""
    import mcp.api.server as server_module

    original_pool = getattr(server_module, "_db_pool", None)
    server_module._db_pool = mock_pool
    server_module.set_db_pool = lambda p: None

    with patch.object(server_module, "_ensure_users_table", new_callable=AsyncMock):
        with patch.object(server_module, "_ensure_sessions_table", new_callable=AsyncMock):
            with patch.object(server_module, "_ensure_messages_table", new_callable=AsyncMock):
                with patch.object(server_module, "_ensure_documents_table", new_callable=AsyncMock):
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
# Document tests
# ---------------------------------------------------------------------------

class TestCreateDocument:
    def test_create_document_minimal(self, client, sample_user):
        """201, document created with defaults."""
        token = _get_token(client, sample_user)
        resp = client.post("/documents/", json={}, headers=_auth_header(token))
        assert resp.status_code == 201, resp.text
        doc = resp.json()["document"]
        assert doc["title"] == "Untitled"
        assert doc["content"] == ""
        assert "id" in doc

    def test_create_document_full(self, client, sample_user):
        """201, document created with all fields."""
        token = _get_token(client, sample_user)
        resp = client.post("/documents/", json={
            "title": "My Research",
            "content": "Some content here.",
            "content_type": "research_note",
        }, headers=_auth_header(token))
        assert resp.status_code == 201, resp.text
        doc = resp.json()["document"]
        assert doc["title"] == "My Research"
        assert doc["content"] == "Some content here."
        assert doc["content_type"] == "research_note"

    def test_create_document_no_auth(self, client):
        """401 if no token."""
        resp = client.post("/documents/", json={})
        assert resp.status_code == 401


class TestListDocuments:
    def test_list_documents_empty(self, client, sample_user):
        """200, empty list for new user."""
        token = _get_token(client, sample_user)
        resp = client.get("/documents/", headers=_auth_header(token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["documents"] == []
        assert data["total"] == 0

    def test_list_documents_with_data(self, client, sample_user):
        """200, returns user's documents."""
        token = _get_token(client, sample_user)
        client.post("/documents/", json={"title": "Doc A"}, headers=_auth_header(token))
        client.post("/documents/", json={"title": "Doc B"}, headers=_auth_header(token))

        resp = client.get("/documents/", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["documents"]) == 2
        assert data["total"] == 2

    def test_list_documents_scoped_to_user(self, client, sample_user, sample_user2):
        """Each user sees only their own documents."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)
        client.post("/documents/", json={"title": "User1 Doc"}, headers=_auth_header(t1))
        client.post("/documents/", json={"title": "User2 Doc"}, headers=_auth_header(t2))

        r1 = client.get("/documents/", headers=_auth_header(t1))
        r2 = client.get("/documents/", headers=_auth_header(t2))
        assert len(r1.json()["documents"]) == 1
        assert len(r2.json()["documents"]) == 1


class TestFilterDocuments:
    def test_filter_by_content_type(self, client, sample_user):
        """200, only matching content_type returned."""
        token = _get_token(client, sample_user)
        client.post("/documents/", json={"title": "Note", "content_type": "research_note"}, headers=_auth_header(token))
        client.post("/documents/", json={"title": "Post", "content_type": "blog_post"}, headers=_auth_header(token))

        resp = client.get("/documents/?content_type=research_note", headers=_auth_header(token))
        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["content_type"] == "research_note"


class TestGetDocument:
    def test_get_document(self, client, sample_user):
        """200, full document returned."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/documents/", json={"title": "My Doc", "content": "Hello"}, headers=_auth_header(token))
        did = create_resp.json()["document"]["id"]

        resp = client.get(f"/documents/{did}", headers=_auth_header(token))
        assert resp.status_code == 200, resp.text
        doc = resp.json()["document"]
        assert doc["title"] == "My Doc"
        assert doc["content"] == "Hello"

    def test_get_other_user_document(self, client, sample_user, sample_user2):
        """403 if document belongs to different user."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)
        create_resp = client.post("/documents/", json={"title": "Mine"}, headers=_auth_header(t1))
        did = create_resp.json()["document"]["id"]

        resp = client.get(f"/documents/{did}", headers=_auth_header(t2))
        assert resp.status_code == 403

    def test_get_nonexistent_document(self, client, sample_user):
        """404 if document does not exist."""
        token = _get_token(client, sample_user)
        resp = client.get(f"/documents/{uuid.uuid4()}", headers=_auth_header(token))
        assert resp.status_code == 404


class TestUpdateDocument:
    def test_update_document_partial(self, client, sample_user):
        """200, partial update — only changed fields."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/documents/", json={"title": "Original", "content": "Old"}, headers=_auth_header(token))
        did = create_resp.json()["document"]["id"]

        resp = client.patch(f"/documents/{did}", json={"title": "Updated"}, headers=_auth_header(token))
        assert resp.status_code == 200, resp.text
        doc = resp.json()["document"]
        assert doc["title"] == "Updated"
        # Content should remain unchanged
        assert doc["content"] == "Old"

    def test_update_other_user_document(self, client, sample_user, sample_user2):
        """403 if updating another user's document."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)
        create_resp = client.post("/documents/", json={"title": "Mine"}, headers=_auth_header(t1))
        did = create_resp.json()["document"]["id"]

        resp = client.patch(f"/documents/{did}", json={"title": "Stolen"}, headers=_auth_header(t2))
        assert resp.status_code == 403


class TestDeleteDocument:
    def test_delete_document(self, client, sample_user):
        """204, document deleted."""
        token = _get_token(client, sample_user)
        create_resp = client.post("/documents/", json={"title": "To Delete"}, headers=_auth_header(token))
        did = create_resp.json()["document"]["id"]

        resp = client.delete(f"/documents/{did}", headers=_auth_header(token))
        assert resp.status_code == 204

        # Verify gone
        get_resp = client.get(f"/documents/{did}", headers=_auth_header(token))
        assert get_resp.status_code == 404

    def test_delete_other_user_document(self, client, sample_user, sample_user2):
        """403 if deleting another user's document."""
        t1 = _get_token(client, sample_user)
        t2 = _get_token(client, sample_user2)
        create_resp = client.post("/documents/", json={"title": "Mine"}, headers=_auth_header(t1))
        did = create_resp.json()["document"]["id"]

        resp = client.delete(f"/documents/{did}", headers=_auth_header(t2))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user():
    return {"email": "test@example.com", "password": "securepass123", "display_name": "Test User"}


@pytest.fixture
def sample_user2():
    return {"email": "other@example.com", "password": "anotherpass456", "display_name": "Other User"}
