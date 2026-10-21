"""models.py — dataclass models for api-mcp (auth, sessions, docs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class User:
    """User account for JWT authentication."""

    id: UUID = field(default_factory=uuid4)
    email: str = ""
    display_name: str = ""
    password_hash: str = ""
    is_admin: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
        }


@dataclass
class ChatSession:
    """Chat session — groups messages under a user."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    title: str = "New Chat"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class ChatMessage:
    """A single message within a chat session."""

    id: UUID = field(default_factory=uuid4)
    session_id: UUID = field(default_factory=uuid4)
    role: str = "user"  # user, assistant, system
    content: str = ""
    tool_calls: dict | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Document:
    """User-owned document for the Report surface."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    session_id: UUID | None = None
    title: str = "Untitled"
    content: str = ""
    content_type: str | None = None
    metadata: dict | None = None
    is_published: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
