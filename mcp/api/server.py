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
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator

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
    """Startup: ensure tables exist. Shutdown: no-op."""
    await _ensure_users_table()
    yield


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
            count_row = await _db_pool.fetchval("SELECT COUNT(*) FROM users")
            checks = {"database": "connected", "users_count": count_row or 0}
        except Exception:
            checks = {"database": "error"}
    return {"status": "ok", "service": "api-mcp", "checks": checks}


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

