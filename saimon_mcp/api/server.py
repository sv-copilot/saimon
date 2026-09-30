"""server.py — api-mcp FastAPI application.

Provides auth endpoints: register, login, token refresh, me.
Also provides health check. This service is the foundation for the
Research UI and Cockpit UI multi-user support.

Auth approach:
- JWT (PyJWT, HS256) for user-facing endpoints
- Separate from research_shared.auth.AuthValidator (API key auth for MCP-to-MCP)
"""

from __future__ import annotations

import os as _os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator

from research_shared.db import DatabaseConfig, DatabasePool

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

_JWT_SECRET = _os.environ.get("SAIMON_JWT_SECRET", "dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 30
_REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------------------------------------------------------------------------
# pydantic models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def display_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("display_name must not be empty")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool = False


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: create DB pool, ensure tables exist. Shutdown: close pool."""
    global _db_pool

    # Create database pool from environment
    database_url = _os.environ.get("DATABASE_URL")
    if database_url:
        try:
            config = DatabaseConfig(database_url=database_url)
            _db_pool = DatabasePool(config)
            # Test connection — lazy init will connect on first query
            await _db_pool.fetchval("SELECT 1")
            await _ensure_users_table()
            await _ensure_sessions_table()
            await _ensure_messages_table()
            await _ensure_documents_table()
        except Exception as e:  # noqa: BLE001 — fail-soft on DB init; log and continue
            import logging
            logging.getLogger("saimon.api").warning("DB init failed: %s", e)
            _db_pool = None

    yield

    # Shutdown: close pool
    if _db_pool is not None:
        try:
            await _db_pool.close()
        except Exception:  # noqa: BLE001, S110 — best-effort close on shutdown
            pass
        _db_pool = None


app = FastAPI(title="api-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# backend injection
# ---------------------------------------------------------------------------

_db_pool: Any = None


def set_db_pool(pool: Any) -> None:
    """Inject a DatabasePool for live DB access."""
    global _db_pool
    _db_pool = pool


async def _ensure_users_table() -> None:
    """Create users + refresh_tokens tables if they don't exist."""
    if _db_pool is None:
        return
    await _db_pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await _db_pool.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            token TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


async def _ensure_sessions_table() -> None:
    """Create chat_sessions table if it doesn't exist."""
    if _db_pool is None:
        return
    await _db_pool.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await _db_pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id)
    """)


async def _ensure_messages_table() -> None:
    """Create chat_messages table if it doesn't exist."""
    if _db_pool is None:
        return
    await _db_pool.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            tool_calls JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await _db_pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id)
    """)


async def _ensure_documents_table() -> None:
    """Create the api-mcp ``documents`` table if it doesn't exist.

    NOTE: this is the *per-user* document store for the Research/Cockpit UI
    (SAIMON-DOCUMENTS-1), NOT the fulltext store.  Fulltext lives in
    ``knowledge_graph_nodes`` as ``fulltext_document`` + ``fulltext_chunk``
    nodes (see ``research_shared.fulltext``); it does not use this table.
    """
    if _db_pool is None:
        return
    await _db_pool.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT 'Untitled',
            content TEXT NOT NULL DEFAULT '',
            content_type TEXT,
            metadata JSONB,
            is_published BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await _db_pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id)
    """)
    await _db_pool.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_session_id ON documents(session_id)
    """)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _create_access_token(user_id: str, email: str) -> str:
    """Create a short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": now + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
        "type": "access",
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _create_refresh_token(user_id: str) -> str:
    """Create a longer-lived JWT refresh token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "exp": now + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": now,
        "type": "refresh",
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT middleware dependency
# ---------------------------------------------------------------------------

async def _get_current_user(request: Request) -> dict:
    """Extract and validate Bearer token, return user dict from DB."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]  # strip "Bearer "
    try:
        payload = _decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token is not an access token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Look up user in DB
    if _db_pool is not None:
        row = await _db_pool.fetchrow(
            "SELECT id, email, display_name, is_admin FROM users WHERE id = $1",
            user_id,
        )
        if row is None:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(row)

    raise HTTPException(status_code=401, detail="Database not available")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    checks = {"database": "not connected"}
    if _db_pool is not None:
        try:
            users_count = await _db_pool.fetchval("SELECT COUNT(*) FROM users") or 0
            sessions_count = 0
            documents_count = 0
            try:
                sessions_count = await _db_pool.fetchval("SELECT COUNT(*) FROM chat_sessions") or 0
            except Exception:  # noqa: BLE001 — optional table may not exist yet
                sessions_count = 0
            try:
                documents_count = await _db_pool.fetchval("SELECT COUNT(*) FROM documents") or 0
            except Exception:  # noqa: BLE001 — optional table may not exist yet
                documents_count = 0
            checks = {
                "database": "connected",
                "users_count": users_count,
                "sessions_count": sessions_count,
                "documents_count": documents_count,
            }
        except Exception:  # noqa: BLE001 — degrade to error state on any DB failure
            checks = {"database": "error"}
    return {"status": "ok", "service": "api-mcp", "checks": checks}


@app.get("/health/s3")
async def health_s3():
    """Report S3 object-storage connectivity (never raises)."""
    from research_shared.s3_storage import S3Storage

    storage = S3Storage.from_env()
    s3 = storage.health_check()
    status = "ok" if s3.get("s3") == "connected" else "degraded"
    return {"status": status, "service": "api-mcp", "s3": s3}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
async def register(body: RegisterRequest):
    """Register a new user account."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Check for existing email
    existing = await _db_pool.fetchrow(
        "SELECT id FROM users WHERE email = $1", body.email
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    # Hash password and insert
    password_hash = _hash_password(body.password)
    user_id = uuid4()

    await _db_pool.execute(
        "INSERT INTO users (id, email, display_name, password_hash) VALUES ($1, $2, $3, $4)",
        user_id,
        body.email,
        body.display_name,
        password_hash,
    )

    return {
        "user": {
            "id": str(user_id),
            "email": body.email,
            "display_name": body.display_name,
        }
    }


@app.post("/auth/login")
async def login(body: LoginRequest):
    """Authenticate user and return JWT tokens."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    row = await _db_pool.fetchrow(
        "SELECT id, email, display_name, password_hash, is_admin FROM users WHERE email = $1",
        body.email,
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = str(row["id"])

    # Create tokens
    access_token = _create_access_token(user_id, row["email"])
    refresh_token = _create_refresh_token(user_id)

    # Store refresh token in DB
    refresh_payload = _decode_token(refresh_token)
    expires_at = datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc)
    await _db_pool.execute(
        "INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES ($1, $2, $3)",
        refresh_payload["jti"],
        user_id,
        expires_at,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": row["email"],
            "display_name": row["display_name"],
            "is_admin": row["is_admin"],
        },
    }


@app.post("/auth/token")
async def token(body: TokenRefreshRequest):
    """Refresh an access token using a refresh token."""
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        payload = _decode_token(body.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token is not a refresh token")

    # Verify refresh token exists in DB
    jti = payload.get("jti")
    if jti:
        stored = await _db_pool.fetchrow(
            "SELECT user_id FROM refresh_tokens WHERE token = $1", jti
        )
        if stored is None:
            raise HTTPException(status_code=401, detail="Refresh token not found")

    user_id = payload.get("sub")
    email = payload.get("email", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token payload")

    # Look up email if not in payload (refresh tokens may not carry email)
    if not email:
        row = await _db_pool.fetchrow(
            "SELECT email FROM users WHERE id = $1", user_id
        )
        if row:
            email = row["email"]

    access_token = _create_access_token(str(user_id), email)
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/auth/me")
async def me(request: Request):
    """Return the authenticated user's profile."""
    user = await _get_current_user(request)
    return {
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "display_name": user["display_name"],
            "is_admin": user.get("is_admin", False),
        }
    }


# ---------------------------------------------------------------------------
# Pydantic models — sessions
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class UpdateSessionRequest(BaseModel):
    title: str


class AddMessageRequest(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("role must be one of: user, assistant, system")
        return v


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------

@app.post("/sessions/", status_code=201)
async def create_session(request: Request, body: CreateSessionRequest | None = None):
    """Create a new chat session for the authenticated user."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    title = body.title if body else "New Chat"

    session_id = uuid4()
    user_id = str(user["id"])

    await _db_pool.execute(
        "INSERT INTO chat_sessions (id, user_id, title) VALUES ($1, $2, $3)",
        session_id,
        user_id,
        title,
    )

    return {
        "session": {
            "id": str(session_id),
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }


@app.get("/sessions/")
async def list_sessions(request: Request):
    """List current user's sessions, ordered by updated_at DESC."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])
    rows = await _db_pool.fetch(
        """SELECT cs.id, cs.title, cs.updated_at,
                  (SELECT COUNT(*) FROM chat_messages WHERE session_id = cs.id) as message_count
           FROM chat_sessions cs
           WHERE cs.user_id = $1
           ORDER BY cs.updated_at DESC""",
        user_id,
    )

    sessions = [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            "message_count": row.get("message_count", 0),
        }
        for row in rows
    ]

    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a session with all its messages."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    # Fetch session
    session_row = await _db_pool.fetchrow(
        "SELECT id, user_id, title, created_at, updated_at FROM chat_sessions WHERE id = $1",
        session_id,
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch messages
    message_rows = await _db_pool.fetch(
        "SELECT id, session_id, role, content, tool_calls, created_at FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC",
        session_id,
    )

    def _serialize(val):
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return str(val) if val is not None else None

    return {
        "session": {
            "id": str(session_row["id"]),
            "user_id": str(session_row["user_id"]),
            "title": session_row["title"],
            "created_at": _serialize(session_row["created_at"]),
            "updated_at": _serialize(session_row["updated_at"]),
        },
        "messages": [
            {
                "id": str(m["id"]),
                "session_id": str(m["session_id"]),
                "role": m["role"],
                "content": m["content"],
                "tool_calls": m.get("tool_calls"),
                "created_at": _serialize(m["created_at"]),
            }
            for m in message_rows
        ],
    }


@app.post("/sessions/{session_id}/messages", status_code=201)
async def add_message(session_id: str, body: AddMessageRequest, request: Request):
    """Add a message to a chat session."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    # Verify session ownership
    session_row = await _db_pool.fetchrow(
        "SELECT id, user_id FROM chat_sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    message_id = uuid4()

    await _db_pool.execute(
        "INSERT INTO chat_messages (id, session_id, role, content) VALUES ($1, $2, $3, $4)",
        message_id,
        session_id,
        body.role,
        body.content,
    )

    # Update session updated_at
    await _db_pool.execute(
        "UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1", session_id
    )

    return {
        "message": {
            "id": str(message_id),
            "session_id": session_id,
            "role": body.role,
            "content": body.content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }


@app.patch("/sessions/{session_id}")
async def update_session(session_id: str, body: UpdateSessionRequest, request: Request):
    """Update a session's title."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    session_row = await _db_pool.fetchrow(
        "SELECT id, user_id FROM chat_sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _db_pool.execute(
        "UPDATE chat_sessions SET title = $1, updated_at = NOW() WHERE id = $2",
        body.title,
        session_id,
    )

    # Return updated session
    updated = await _db_pool.fetchrow(
        "SELECT id, user_id, title, created_at, updated_at FROM chat_sessions WHERE id = $1",
        session_id,
    )

    def _serialize(val):
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return str(val) if val is not None else None

    return {
        "session": {
            "id": str(updated["id"]),
            "user_id": str(updated["user_id"]),
            "title": updated["title"],
            "created_at": _serialize(updated["created_at"]),
            "updated_at": _serialize(updated["updated_at"]),
        }
    }


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request):
    """Delete a session and all its messages (CASCADE)."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    session_row = await _db_pool.fetchrow(
        "SELECT id, user_id FROM chat_sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _db_pool.execute("DELETE FROM chat_sessions WHERE id = $1", session_id)


# ---------------------------------------------------------------------------
# Pydantic models — documents
# ---------------------------------------------------------------------------

class CreateDocumentRequest(BaseModel):
    title: str = "Untitled"
    content: str = ""
    content_type: str | None = None
    session_id: str | None = None


class UpdateDocumentRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    metadata: dict | None = None


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------

def _serialize_dt(val):
    """Serialize datetime values for JSON responses."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val) if val is not None else None


@app.post("/documents/", status_code=201)
async def create_document(body: CreateDocumentRequest, request: Request):
    """Create a new document for the authenticated user."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    doc_id = uuid4()
    user_id = str(user["id"])

    await _db_pool.execute(
        """INSERT INTO documents (id, user_id, session_id, title, content, content_type)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        doc_id, user_id, body.session_id, body.title, body.content, body.content_type,
    )

    return {
        "document": {
            "id": str(doc_id),
            "user_id": user_id,
            "title": body.title,
            "content": body.content,
            "content_type": body.content_type,
            "session_id": body.session_id,
            "is_published": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


@app.get("/documents/")
async def list_documents(
    request: Request,
    content_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """List current user's documents, ordered by updated_at DESC."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    if content_type:
        rows = await _db_pool.fetch(
            """SELECT id, user_id, session_id, title, content, content_type, metadata,
                      is_published, created_at, updated_at
               FROM documents
               WHERE user_id = $1 AND content_type = $2
               ORDER BY updated_at DESC
               LIMIT $3 OFFSET $4""",
            user_id, content_type, limit, offset,
        )
        total = await _db_pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE user_id = $1 AND content_type = $2",
            user_id, content_type,
        )
    else:
        rows = await _db_pool.fetch(
            """SELECT id, user_id, session_id, title, content, content_type, metadata,
                      is_published, created_at, updated_at
               FROM documents
               WHERE user_id = $1
               ORDER BY updated_at DESC
               LIMIT $2 OFFSET $3""",
            user_id, limit, offset,
        )
        total = await _db_pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE user_id = $1", user_id
        )

    documents = [
        {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "session_id": str(row["session_id"]) if row.get("session_id") else None,
            "title": row["title"],
            "content": row["content"],
            "content_type": row.get("content_type"),
            "metadata": row.get("metadata"),
            "is_published": row.get("is_published", False),
            "created_at": _serialize_dt(row["created_at"]),
            "updated_at": _serialize_dt(row["updated_at"]),
        }
        for row in rows
    ]

    return {"documents": documents, "total": total or 0}


@app.get("/documents/{document_id}")
async def get_document(document_id: str, request: Request):
    """Get a single document by ID."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    row = await _db_pool.fetchrow(
        """SELECT id, user_id, session_id, title, content, content_type, metadata,
                  is_published, created_at, updated_at
           FROM documents WHERE id = $1""",
        document_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "document": {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "session_id": str(row["session_id"]) if row.get("session_id") else None,
            "title": row["title"],
            "content": row["content"],
            "content_type": row.get("content_type"),
            "metadata": row.get("metadata"),
            "is_published": row.get("is_published", False),
            "created_at": _serialize_dt(row["created_at"]),
            "updated_at": _serialize_dt(row["updated_at"]),
        }
    }


@app.patch("/documents/{document_id}")
async def update_document(document_id: str, body: UpdateDocumentRequest, request: Request):
    """Partially update a document."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    doc_row = await _db_pool.fetchrow(
        "SELECT id, user_id FROM documents WHERE id = $1", document_id
    )
    if doc_row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Build SET clause dynamically for partial update
    updates = []
    params = []
    if body.title is not None:
        updates.append("title = $1")
        params.append(body.title)
    if body.content is not None:
        idx = len(params) + 1
        updates.append(f"content = ${idx}")
        params.append(body.content)
    if body.metadata is not None:
        import json as _json
        idx = len(params) + 1
        updates.append(f"metadata = ${idx}")
        params.append(_json.dumps(body.metadata))

    if updates:
        updates.append("updated_at = NOW()")
        set_clause = ", ".join(updates)
        params.append(document_id)
        idx = len(params)
        await _db_pool.execute(
            f"UPDATE documents SET {set_clause} WHERE id = ${idx}",
            *params,
        )

    # Return updated document
    updated = await _db_pool.fetchrow(
        """SELECT id, user_id, session_id, title, content, content_type, metadata,
                  is_published, created_at, updated_at
           FROM documents WHERE id = $1""",
        document_id,
    )

    return {
        "document": {
            "id": str(updated["id"]),
            "user_id": str(updated["user_id"]),
            "session_id": str(updated["session_id"]) if updated.get("session_id") else None,
            "title": updated["title"],
            "content": updated["content"],
            "content_type": updated.get("content_type"),
            "metadata": updated.get("metadata"),
            "is_published": updated.get("is_published", False),
            "created_at": _serialize_dt(updated["created_at"]),
            "updated_at": _serialize_dt(updated["updated_at"]),
        }
    }


@app.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request):
    """Delete a document."""
    user = await _get_current_user(request)
    if _db_pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    user_id = str(user["id"])

    doc_row = await _db_pool.fetchrow(
        "SELECT id, user_id FROM documents WHERE id = $1", document_id
    )
    if doc_row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if str(doc_row["user_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _db_pool.execute("DELETE FROM documents WHERE id = $1", document_id)

