"""seed_loader.py — database re-seeding from canonical seed data.

Provides a SeedLoader that loads content types, voice profiles, and seed
requests from seed_data.py into the PostgreSQL knowledge graph.  All
operations are idempotent (ON CONFLICT upserts) so the platform can
survive a DB wipe and re-seed cleanly.
"""

from __future__ import annotations

import json
from typing import Any

from research_shared.seed_data import (
    CONTENT_TYPES,
    SEED_REQUESTS,
    VOICE_PROFILES,
)

# ---------------------------------------------------------------------------
# SeedLoader
# ---------------------------------------------------------------------------

class SeedLoader:
    """Loads canonical seed data into PostgreSQL tables.

    All load methods are idempotent — they use INSERT ... ON CONFLICT so
    re-running on an existing database is safe and updates stale rows.
    """

    def __init__(self, db: Any) -> None:
        """Create a SeedLoader backed by a DatabasePool.

        Args:
            db: A DatabasePool-like object with an async ``execute`` method.
        """
        self._db = db

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def load_all(self) -> dict[str, Any]:
        """Load all seed data: content types, voice profiles, seed requests.

        Returns:
            Dict with keys ``content_types``, ``voice_profiles``,
            ``seed_requests``, each containing ``{"loaded": N}``.
        """
        ct = await self.load_content_types()
        vp = await self.load_voice_profiles()
        sr = await self.load_seed_requests()
        return {
            "content_types": ct,
            "voice_profiles": vp,
            "seed_requests": sr,
        }

    async def load_content_types(self) -> dict[str, Any]:
        """Upsert all CONTENT_TYPES into the content_type_registry table.

        Returns:
            ``{"loaded": N}``.
        """
        for ct in CONTENT_TYPES:
            await self._db.execute(
                "INSERT INTO content_type_registry "
                "(name, description, required_params, optional_params, voice_profile) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (name) DO UPDATE SET "
                "description = EXCLUDED.description, "
                "required_params = EXCLUDED.required_params, "
                "optional_params = EXCLUDED.optional_params, "
                "voice_profile = EXCLUDED.voice_profile, "
                "updated_at = now()",
                ct["name"],
                ct["description"],
                json.dumps(ct["required_params"]),
                json.dumps(ct["optional_params"]),
                ct.get("voice_profile"),
            )
        return {"loaded": len(CONTENT_TYPES)}

    async def load_voice_profiles(self) -> dict[str, Any]:
        """Upsert all VOICE_PROFILES into the voice_profiles table.

        Returns:
            ``{"loaded": N}``.
        """
        for vp in VOICE_PROFILES:
            await self._db.execute(
                "INSERT INTO voice_profiles (name, description, tone, style_guide) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (name) DO UPDATE SET "
                "description = EXCLUDED.description, "
                "tone = EXCLUDED.tone, "
                "style_guide = EXCLUDED.style_guide",
                vp["name"],
                vp["description"],
                vp["tone"],
                vp.get("style_guide"),
            )
        return {"loaded": len(VOICE_PROFILES)}

    async def load_seed_requests(self) -> dict[str, Any]:
        """Insert all SEED_REQUESTS into the seed_requests table.

        Only inserts rows that don't already exist (matched by content_type
        + prompt).  Existing rows are left untouched to preserve status.

        Returns:
            ``{"loaded": N}``.
        """
        for sr in SEED_REQUESTS:
            await self._db.execute(
                "INSERT INTO seed_requests (content_type, prompt, parameters, status) "
                "VALUES ($1, $2, $3, 'pending') "
                "ON CONFLICT DO NOTHING",
                sr["content_type"],
                sr["prompt"],
                json.dumps(sr.get("parameters", {})),
            )
        return {"loaded": len(SEED_REQUESTS)}
