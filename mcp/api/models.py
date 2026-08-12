"""models.py — SQLAlchemy-style models for api-mcp (auth, sessions, docs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass
class User:
    """User account for JWT authentication."""

    id: UUID = field(default_factory=uuid4)
    email: str = ""
    display_name: str = ""
    password_hash: str = ""
    is_admin: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
        }
