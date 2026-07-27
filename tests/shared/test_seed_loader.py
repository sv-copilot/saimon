"""Tests for research_shared.seed_loader — DB re-seeding from seed_data."""

import pytest

from research_shared.seed_data import (
    CONTENT_TYPES,
    SEED_REQUESTS,
    VOICE_PROFILES,
)

# ---------------------------------------------------------------------------
# SeedLoader exists and has expected interface
# ---------------------------------------------------------------------------

class TestSeedLoaderExists:
    """SeedLoader module and class must exist with the expected API."""

    def test_module_importable(self):
        """seed_loader module is importable."""
        from research_shared import seed_loader
        assert seed_loader is not None

    def test_seed_loader_class_exists(self):
        """SeedLoader class is defined."""
        from research_shared.seed_loader import SeedLoader
        assert SeedLoader is not None

    def test_seed_loader_accepts_db(self):
        """SeedLoader can be constructed with a DatabasePool."""
        from research_shared.seed_loader import SeedLoader

        class FakePool:
            async def execute(self, *args):
                return "OK"
            async def fetch(self, *args):
                return []

        loader = SeedLoader(db=FakePool())
        assert loader is not None

    def test_seed_loader_has_expected_methods(self):
        """SeedLoader exposes load_all, load_content_types, load_voice_profiles,
        load_seed_requests."""
        from research_shared.seed_loader import SeedLoader

        for method in (
            "load_all",
            "load_content_types",
            "load_voice_profiles",
            "load_seed_requests",
        ):
            assert hasattr(SeedLoader, method), f"Missing: {method}"
            import inspect
            assert inspect.iscoroutinefunction(
                getattr(SeedLoader, method)
            ), f"{method} must be a coroutine function"


# ---------------------------------------------------------------------------
# SeedLoader — mock-backed functional tests
# ---------------------------------------------------------------------------

class _TrackingPool:
    """A fake DatabasePool that records INSERT calls."""

    def __init__(self):
        self.executed = []  # list of (query, args)
        self._inserted_ids = iter(range(1, 1000))

    async def execute(self, query, *args):
        self.executed.append((query, args))
        next_id = next(self._inserted_ids)
        return f"INSERT {next_id} 1"

    async def fetch(self, query, *args):
        return []

    async def fetchrow(self, query, *args):
        return None

    async def fetchval(self, query, *args):
        return None


class TestSeedLoaderLoadContentTypes:
    @pytest.mark.asyncio
    async def test_inserts_all_content_types(self):
        """load_content_types inserts every CONTENT_TYPE from seed_data."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        result = await loader.load_content_types()

        assert result["loaded"] == len(CONTENT_TYPES)
        assert len(pool.executed) == len(CONTENT_TYPES)

        # Every content type name appears in at least one INSERT
        all_names = set()
        for query, args in pool.executed:
            all_names.add(args[0])
        seed_names = {ct["name"] for ct in CONTENT_TYPES}
        assert seed_names == all_names

    @pytest.mark.asyncio
    async def test_uses_upsert_semantics(self):
        """INSERT statements use ON CONFLICT for idempotency."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_content_types()

        for query, _args in pool.executed:
            assert "ON CONFLICT" in query, (
                f"INSERT must use ON CONFLICT for idempotency: {query[:80]}"
            )

    @pytest.mark.asyncio
    async def test_params_serialized_as_json(self):
        """required_params and optional_params are serialized as JSON strings."""
        import json

        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_content_types()

        for query, args in pool.executed:
            # args[2] = required_params JSON, args[3] = optional_params JSON
            required = args[2]
            optional = args[3]
            assert isinstance(json.loads(required), list)
            assert isinstance(json.loads(optional), list)


class TestSeedLoaderLoadVoiceProfiles:
    @pytest.mark.asyncio
    async def test_inserts_all_voice_profiles(self):
        """load_voice_profiles inserts every VOICE_PROFILE from seed_data."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        result = await loader.load_voice_profiles()

        assert result["loaded"] == len(VOICE_PROFILES)
        assert len(pool.executed) == len(VOICE_PROFILES)

        all_names = set()
        for _query, args in pool.executed:
            all_names.add(args[0])
        seed_names = {vp["name"] for vp in VOICE_PROFILES}
        assert seed_names == all_names

    @pytest.mark.asyncio
    async def test_uses_upsert_semantics(self):
        """INSERT statements use ON CONFLICT for idempotency."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_voice_profiles()

        for query, _args in pool.executed:
            assert "ON CONFLICT" in query


class TestSeedLoaderLoadSeedRequests:
    @pytest.mark.asyncio
    async def test_inserts_all_seed_requests(self):
        """load_seed_requests inserts every SEED_REQUEST from seed_data."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        result = await loader.load_seed_requests()

        assert result["loaded"] == len(SEED_REQUESTS)
        assert len(pool.executed) == len(SEED_REQUESTS)

    @pytest.mark.asyncio
    async def test_seed_requests_have_pending_status(self):
        """Inserted seed requests have status 'pending'."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_seed_requests()

        for query, _args in pool.executed:
            # 'pending' is a SQL literal in the INSERT statement
            assert "pending" in query.lower()

    @pytest.mark.asyncio
    async def test_parameters_serialized_as_json(self):
        """Request parameters are serialized as JSON."""
        import json

        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_seed_requests()

        for _query, args in pool.executed:
            # args[2] = parameters JSONB
            params = args[2]
            assert isinstance(json.loads(params), dict)


class TestSeedLoaderLoadAll:
    @pytest.mark.asyncio
    async def test_load_all_calls_all_three(self):
        """load_all calls content_types, voice_profiles, and seed_requests."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        result = await loader.load_all()

        assert "content_types" in result
        assert "voice_profiles" in result
        assert "seed_requests" in result
        assert result["content_types"]["loaded"] == len(CONTENT_TYPES)
        assert result["voice_profiles"]["loaded"] == len(VOICE_PROFILES)
        assert result["seed_requests"]["loaded"] == len(SEED_REQUESTS)


# ---------------------------------------------------------------------------
# SeedLoader — domain module support
# ---------------------------------------------------------------------------


class TestSeedLoaderWithDomainModules:
    """SeedLoader should accept and load domain config modules."""

    def test_constructor_accepts_domain_modules(self):
        """SeedLoader accepts optional domain_modules parameter."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool, domain_modules=[])
        assert loader is not None
        assert loader._domain_modules == []

    def test_constructor_defaults_domain_modules_to_empty(self):
        """domain_modules defaults to empty list when not provided."""
        from research_shared.seed_loader import SeedLoader

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        assert loader._domain_modules == []

    @pytest.mark.asyncio
    async def test_load_content_types_includes_domain(self):
        """load_content_types merges core + domain content types."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool, domain_modules=[job_hunt_config])
        result = await loader.load_content_types()

        expected_total = len(CONTENT_TYPES) + len(
            job_hunt_config.DOMAIN_CONTENT_TYPES
        )
        assert result["loaded"] == expected_total
        assert result["domain_count"] == len(
            job_hunt_config.DOMAIN_CONTENT_TYPES
        )

    @pytest.mark.asyncio
    async def test_load_voice_profiles_includes_domain(self):
        """load_voice_profiles merges core + domain voice profiles."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool, domain_modules=[job_hunt_config])
        result = await loader.load_voice_profiles()

        expected_total = len(VOICE_PROFILES) + len(
            job_hunt_config.DOMAIN_VOICE_PROFILES
        )
        assert result["loaded"] == expected_total
        assert result["domain_count"] == len(
            job_hunt_config.DOMAIN_VOICE_PROFILES
        )

    @pytest.mark.asyncio
    async def test_load_seed_requests_includes_domain(self):
        """load_seed_requests merges core + domain seed requests."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool, domain_modules=[job_hunt_config])
        result = await loader.load_seed_requests()

        expected_total = len(SEED_REQUESTS) + len(
            job_hunt_config.DOMAIN_SEED_REQUESTS
        )
        assert result["loaded"] == expected_total
        assert result["domain_count"] == len(
            job_hunt_config.DOMAIN_SEED_REQUESTS
        )

    @pytest.mark.asyncio
    async def test_load_domain_loads_single_module(self):
        """load_domain loads a single domain config module."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        result = await loader.load_domain(job_hunt_config)

        assert result["content_types"]["loaded"] == len(
            job_hunt_config.DOMAIN_CONTENT_TYPES
        )
        assert result["voice_profiles"]["loaded"] == len(
            job_hunt_config.DOMAIN_VOICE_PROFILES
        )
        assert result["seed_requests"]["loaded"] == len(
            job_hunt_config.DOMAIN_SEED_REQUESTS
        )

    @pytest.mark.asyncio
    async def test_load_domain_uses_upsert(self):
        """load_domain uses ON CONFLICT for idempotency."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool)
        await loader.load_domain(job_hunt_config)

        for query, _args in pool.executed:
            assert "ON CONFLICT" in query, (
                f"INSERT must use ON CONFLICT: {query[:80]}"
            )

    @pytest.mark.asyncio
    async def test_load_all_includes_domain(self):
        """load_all includes domain data when domain_modules provided."""
        from research_shared.seed_loader import SeedLoader
        from research_shared import job_hunt_config

        pool = _TrackingPool()
        loader = SeedLoader(db=pool, domain_modules=[job_hunt_config])
        result = await loader.load_all()

        expected_ct = len(CONTENT_TYPES) + len(
            job_hunt_config.DOMAIN_CONTENT_TYPES
        )
        expected_vp = len(VOICE_PROFILES) + len(
            job_hunt_config.DOMAIN_VOICE_PROFILES
        )
        expected_sr = len(SEED_REQUESTS) + len(
            job_hunt_config.DOMAIN_SEED_REQUESTS
        )
        assert result["content_types"]["loaded"] == expected_ct
        assert result["voice_profiles"]["loaded"] == expected_vp
        assert result["seed_requests"]["loaded"] == expected_sr

    def test_seed_loader_has_load_domain_method(self):
        """SeedLoader exposes load_domain coroutine method."""
        from research_shared.seed_loader import SeedLoader
        import inspect

        assert hasattr(SeedLoader, "load_domain")
        assert inspect.iscoroutinefunction(SeedLoader.load_domain)
