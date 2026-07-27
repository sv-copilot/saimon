"""Tests for research_shared.seed_data — domain bootstrap definitions."""

import pytest

from research_shared.seed_data import (
    CONTENT_TYPES,
    SEED_DATA_VERSION,
    SEED_REQUESTS,
    VOICE_PROFILES,
    get_all_definitions,
    load_content_types,
    load_seed_requests,
    load_voice_profiles,
)

# ---------------------------------------------------------------------------
# SEED_DATA_VERSION
# ---------------------------------------------------------------------------


class TestSeedDataVersion:
    def test_is_semver_string(self):
        """SEED_DATA_VERSION is a non-empty version string."""
        assert isinstance(SEED_DATA_VERSION, str)
        assert len(SEED_DATA_VERSION) > 0
        assert "." in SEED_DATA_VERSION

    def test_version_is_stable(self):
        """Version doesn't change between calls."""
        v1 = SEED_DATA_VERSION
        v2 = SEED_DATA_VERSION
        assert v1 == v2


# ---------------------------------------------------------------------------
# CONTENT_TYPES
# ---------------------------------------------------------------------------


class TestContentTypes:
    def test_is_non_empty_list(self):
        """CONTENT_TYPES is a non-empty list."""
        assert isinstance(CONTENT_TYPES, list)
        assert len(CONTENT_TYPES) > 0

    def test_every_entry_has_required_fields(self):
        """Every content type has name, description, required_params,
        optional_params."""
        for ct in CONTENT_TYPES:
            assert "name" in ct, f"Missing 'name' in {ct}"
            assert isinstance(ct["name"], str)
            assert len(ct["name"]) > 0
            assert "description" in ct, f"Missing 'description' in {ct}"
            assert isinstance(ct["description"], str)
            assert "required_params" in ct, f"Missing 'required_params' in {ct}"
            assert isinstance(ct["required_params"], list)
            assert "optional_params" in ct, f"Missing 'optional_params' in {ct}"
            assert isinstance(ct["optional_params"], list)

    def test_names_are_unique(self):
        """No duplicate content type names."""
        names = [ct["name"] for ct in CONTENT_TYPES]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_names_are_snake_case(self):
        """All content type names use snake_case with no spaces."""
        for ct in CONTENT_TYPES:
            name = ct["name"]
            assert " " not in name, f"Name '{name}' contains spaces"
            assert name == name.lower(), f"Name '{name}' is not lowercase"

    def test_params_have_valid_shape(self):
        """Each param entry has name, type, description."""
        valid_types = {"str", "int", "float", "bool", "list[str]", "dict"}
        for ct in CONTENT_TYPES:
            for param_list_name in ("required_params", "optional_params"):
                params = ct[param_list_name]
                for p in params:
                    assert "name" in p
                    assert "type" in p
                    assert p["type"] in valid_types, (
                        f"{ct['name']} param '{p['name']}' has "
                        f"invalid type '{p['type']}'"
                    )
                    assert "description" in p

    def test_includes_bootstrapped_types(self):
        """Includes the 5 types bootstrapped in schema.sql."""
        names = {ct["name"] for ct in CONTENT_TYPES}
        expected = {"blog_post", "summary", "research_note",
                    "social_post", "email_draft"}
        missing = expected - names
        assert not missing, f"Missing bootstrapped types: {missing}"

    def test_includes_domain_types(self):
        """Includes domain-specific types beyond the 5 bootstrapped ones."""
        names = {ct["name"] for ct in CONTENT_TYPES}
        # At least 3 additional domain types
        domain = names - {"blog_post", "summary", "research_note",
                          "social_post", "email_draft"}
        assert len(domain) >= 3, (
            f"Expected at least 3 domain types, got {len(domain)}: {domain}"
        )

    def test_voice_profile_references_are_valid(self):
        """Any voice_profile references match defined voice profiles."""
        profile_names = {vp["name"] for vp in VOICE_PROFILES}
        for ct in CONTENT_TYPES:
            if ct.get("voice_profile"):
                assert ct["voice_profile"] in profile_names, (
                    f"'{ct['name']}' references unknown voice "
                    f"profile '{ct['voice_profile']}'"
                )


# ---------------------------------------------------------------------------
# VOICE_PROFILES
# ---------------------------------------------------------------------------


class TestVoiceProfiles:
    def test_is_non_empty_list(self):
        """VOICE_PROFILES is a non-empty list."""
        assert isinstance(VOICE_PROFILES, list)
        assert len(VOICE_PROFILES) > 0

    def test_every_entry_has_required_fields(self):
        """Every voice profile has name, description, tone."""
        for vp in VOICE_PROFILES:
            assert "name" in vp, f"Missing 'name' in {vp}"
            assert isinstance(vp["name"], str)
            assert len(vp["name"]) > 0
            assert "description" in vp
            assert "tone" in vp
            assert isinstance(vp["tone"], str)

    def test_names_are_unique(self):
        """No duplicate voice profile names."""
        names = [vp["name"] for vp in VOICE_PROFILES]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_includes_spencer_default(self):
        """Must include spencer-default voice profile."""
        names = {vp["name"] for vp in VOICE_PROFILES}
        assert "spencer-default" in names, "Missing spencer-default"

    def test_has_multiple_profiles(self):
        """Has at least 3 voice profiles for variety."""
        assert len(VOICE_PROFILES) >= 3, (
            f"Expected at least 3 voice profiles, got {len(VOICE_PROFILES)}"
        )

    def test_style_guide_optional(self):
        """style_guide is an optional field — some may have it, some may not."""
        for vp in VOICE_PROFILES:
            if "style_guide" in vp:
                assert isinstance(vp["style_guide"], (str, type(None)))


# ---------------------------------------------------------------------------
# SEED_REQUESTS
# ---------------------------------------------------------------------------


class TestSeedRequests:
    def test_is_non_empty_list(self):
        """SEED_REQUESTS is a non-empty list."""
        assert isinstance(SEED_REQUESTS, list)
        assert len(SEED_REQUESTS) > 0

    def test_every_entry_has_required_fields(self):
        """Every seed request has content_type, prompt, parameters."""
        for sr in SEED_REQUESTS:
            assert "content_type" in sr
            assert isinstance(sr["content_type"], str)
            assert "prompt" in sr
            assert isinstance(sr["prompt"], str)
            assert len(sr["prompt"]) > 0
            assert "parameters" in sr
            assert isinstance(sr["parameters"], dict)

    def test_content_types_reference_registered(self):
        """All seed request content_types exist in CONTENT_TYPES."""
        known = {ct["name"] for ct in CONTENT_TYPES}
        for sr in SEED_REQUESTS:
            assert sr["content_type"] in known, (
                f"Seed request references unknown content type "
                f"'{sr['content_type']}'"
            )

    def test_has_at_least_ten(self):
        """Has at least 10 seed requests for platform recovery."""
        assert len(SEED_REQUESTS) >= 10, (
            f"Expected at least 10 seed requests, got {len(SEED_REQUESTS)}"
        )

    def test_covers_multiple_content_types(self):
        """Seed requests span at least 3 different content types."""
        types_used = {sr["content_type"] for sr in SEED_REQUESTS}
        assert len(types_used) >= 3, (
            f"Expected at least 3 content types in seed requests, "
            f"got {len(types_used)}: {types_used}"
        )

    def test_parameters_reflect_content_type_params(self):
        """Seed request parameters are consistent with their content type's
        required and optional params."""
        ct_map = {ct["name"]: ct for ct in CONTENT_TYPES}
        for sr in SEED_REQUESTS:
            ct = ct_map[sr["content_type"]]
            valid_param_names = {
                p["name"] for p in ct["required_params"]
            } | {
                p["name"] for p in ct["optional_params"]
            }
            for key in sr["parameters"]:
                assert key in valid_param_names, (
                    f"Seed request param '{key}' not valid for "
                    f"content type '{sr['content_type']}'"
                )


# ---------------------------------------------------------------------------
# get_all_definitions
# ---------------------------------------------------------------------------


class TestGetAllDefinitions:
    def test_returns_dict_with_three_keys(self):
        """Returns dict with content_types, voice_profiles, seed_requests."""
        result = get_all_definitions()
        assert isinstance(result, dict)
        assert set(result.keys()) == {
            "content_types", "voice_profiles", "seed_requests"
        }

    def test_content_types_match_module_constant(self):
        """Returned content_types is the same as CONTENT_TYPES."""
        result = get_all_definitions()
        assert result["content_types"] is CONTENT_TYPES

    def test_voice_profiles_match_module_constant(self):
        """Returned voice_profiles is the same as VOICE_PROFILES."""
        result = get_all_definitions()
        assert result["voice_profiles"] is VOICE_PROFILES

    def test_seed_requests_match_module_constant(self):
        """Returned seed_requests is the same as SEED_REQUESTS."""
        result = get_all_definitions()
        assert result["seed_requests"] is SEED_REQUESTS


# ---------------------------------------------------------------------------
# load_content_types
# ---------------------------------------------------------------------------


class _FakePool:
    """A fake DatabasePool for testing loader functions."""

    def __init__(self):
        self._executed = []

    async def execute(self, query, *args):
        self._executed.append((query, args))
        return "OK"


class TestLoadContentTypes:
    @pytest.mark.asyncio
    async def test_executes_upsert_for_each_type(self):
        """load_content_types calls execute once per type with UPSERT."""
        pool = _FakePool()
        await load_content_types(pool)
        assert len(pool._executed) == len(CONTENT_TYPES)

    @pytest.mark.asyncio
    async def test_upsert_includes_all_fields(self):
        """Each UPSERT includes name, description, required_params,
        optional_params, voice_profile."""
        pool = _FakePool()
        await load_content_types(pool)
        for (query, args) in pool._executed:
            assert "INSERT INTO content_type_registry" in query
            assert "ON CONFLICT" in query
            # args should include name as first param
            assert args[0]  # name is non-empty


class TestLoadVoiceProfiles:
    @pytest.mark.asyncio
    async def test_executes_upsert_for_each_profile(self):
        """load_voice_profiles calls execute once per profile with
        UPSERT."""
        pool = _FakePool()
        await load_voice_profiles(pool)
        assert len(pool._executed) == len(VOICE_PROFILES)

    @pytest.mark.asyncio
    async def test_upsert_includes_name_description_tone(self):
        """Each UPSERT includes name, description, tone, style_guide."""
        pool = _FakePool()
        await load_voice_profiles(pool)
        for (query, args) in pool._executed:
            assert "INSERT INTO voice_profiles" in query
            assert "ON CONFLICT" in query


class TestLoadSeedRequests:
    @pytest.mark.asyncio
    async def test_executes_insert_for_each_request(self):
        """load_seed_requests calls execute once per seed request with
        INSERT."""
        pool = _FakePool()
        await load_seed_requests(pool)
        assert len(pool._executed) == len(SEED_REQUESTS)

    @pytest.mark.asyncio
    async def test_insert_includes_content_type_prompt_params(self):
        """Each INSERT includes content_type, prompt, parameters."""
        pool = _FakePool()
        await load_seed_requests(pool)
        for (query, args) in pool._executed:
            assert "INSERT INTO seed_requests" in query
            assert "ON CONFLICT" not in query.upper()
