"""seed_loader.py — database re-seeding from canonical seed data.

Provides a SeedLoader that loads content types, voice profiles, and seed
requests from seed_data.py into the PostgreSQL knowledge graph.  All
operations are idempotent (ON CONFLICT upserts) so the platform can
survive a DB wipe and re-seed cleanly.

Domain tools can inject their own config modules (e.g. job_hunt_config)
via the ``domain_modules`` parameter.  These are loaded alongside the
canonical seed data without polluting the platform core.
"""

from __future__ import annotations

import json
from types import ModuleType
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

    Accepts optional ``domain_modules`` — a list of Python modules that
    export ``DOMAIN_CONTENT_TYPES``, ``DOMAIN_VOICE_PROFILES``, and
    ``DOMAIN_SEED_REQUESTS`` following the same shape as seed_data.py.
    """

    def __init__(
        self,
        db: Any,
        domain_modules: list[ModuleType] | None = None,
    ) -> None:
        """Create a SeedLoader backed by a DatabasePool.

        Args:
            db: A DatabasePool-like object with an async ``execute`` method.
            domain_modules: Optional list of domain config modules
                (e.g. ``[job_hunt_config]``).  Each must export
                ``DOMAIN_CONTENT_TYPES``, ``DOMAIN_VOICE_PROFILES``,
                and ``DOMAIN_SEED_REQUESTS``.
        """
        self._db = db
        self._domain_modules: list[ModuleType] = domain_modules or []

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _all_content_types(self) -> list[dict[str, Any]]:
        """Merge core + domain content types."""
        merged = list(CONTENT_TYPES)
        for mod in self._domain_modules:
            if hasattr(mod, "DOMAIN_CONTENT_TYPES"):
                merged.extend(mod.DOMAIN_CONTENT_TYPES)
        return merged

    def _all_voice_profiles(self) -> list[dict[str, Any]]:
        """Merge core + domain voice profiles."""
        merged = list(VOICE_PROFILES)
        for mod in self._domain_modules:
            if hasattr(mod, "DOMAIN_VOICE_PROFILES"):
                merged.extend(mod.DOMAIN_VOICE_PROFILES)
        return merged

    def _all_seed_requests(self) -> list[dict[str, Any]]:
        """Merge core + domain seed requests."""
        merged = list(SEED_REQUESTS)
        for mod in self._domain_modules:
            if hasattr(mod, "DOMAIN_SEED_REQUESTS"):
                merged.extend(mod.DOMAIN_SEED_REQUESTS)
        return merged

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def load_all(self) -> dict[str, Any]:
        """Load all seed data: content types, voice profiles, seed requests.

        Includes domain modules if any were provided at construction.

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
        """Upsert all CONTENT_TYPES (core + domain) into the
        content_type_registry table.

        Returns:
            ``{"loaded": N, "domain_count": M}``.
        """
        all_types = self._all_content_types()
        for ct in all_types:
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
        domain_count = len(all_types) - len(CONTENT_TYPES)
        return {"loaded": len(all_types), "domain_count": domain_count}

    async def load_voice_profiles(self) -> dict[str, Any]:
        """Upsert all VOICE_PROFILES (core + domain) into the
        voice_profiles table.

        Returns:
            ``{"loaded": N, "domain_count": M}``.
        """
        all_profiles = self._all_voice_profiles()
        for vp in all_profiles:
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
        domain_count = len(all_profiles) - len(VOICE_PROFILES)
        return {"loaded": len(all_profiles), "domain_count": domain_count}

    async def load_seed_requests(self) -> dict[str, Any]:
        """Insert all SEED_REQUESTS (core + domain) into the seed_requests
        table.

        Only inserts rows that don't already exist (matched by content_type
        + prompt).  Existing rows are left untouched to preserve status.

        Returns:
            ``{"loaded": N, "domain_count": M}``.
        """
        all_requests = self._all_seed_requests()
        for sr in all_requests:
            await self._db.execute(
                "INSERT INTO seed_requests (content_type, prompt, parameters, status) "
                "VALUES ($1, $2, $3, 'pending') "
                "ON CONFLICT DO NOTHING",
                sr["content_type"],
                sr["prompt"],
                json.dumps(sr.get("parameters", {})),
            )
        domain_count = len(all_requests) - len(SEED_REQUESTS)
        return {"loaded": len(all_requests), "domain_count": domain_count}

    async def load_domain(self, domain_module: ModuleType) -> dict[str, Any]:
        """Load seed data from a single domain config module.

        Useful for loading a domain on demand without re-loading core data.

        Args:
            domain_module: A module exporting DOMAIN_CONTENT_TYPES,
                DOMAIN_VOICE_PROFILES, and DOMAIN_SEED_REQUESTS.

        Returns:
            Dict with keys ``content_types``, ``voice_profiles``,
            ``seed_requests``, each containing ``{"loaded": N}``.
        """
        domain_ct = getattr(domain_module, "DOMAIN_CONTENT_TYPES", [])
        domain_vp = getattr(domain_module, "DOMAIN_VOICE_PROFILES", [])
        domain_sr = getattr(domain_module, "DOMAIN_SEED_REQUESTS", [])

        for ct in domain_ct:
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

        for vp in domain_vp:
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

        for sr in domain_sr:
            await self._db.execute(
                "INSERT INTO seed_requests (content_type, prompt, parameters, status) "
                "VALUES ($1, $2, $3, 'pending') "
                "ON CONFLICT DO NOTHING",
                sr["content_type"],
                sr["prompt"],
                json.dumps(sr.get("parameters", {})),
            )

        return {
            "content_types": {"loaded": len(domain_ct)},
            "voice_profiles": {"loaded": len(domain_vp)},
            "seed_requests": {"loaded": len(domain_sr)},
        }
