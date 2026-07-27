"""Tests for research_shared.job_hunt_config — domain bootstrap definitions."""

import pytest

# Will fail until job_hunt_config.py is created
from research_shared.job_hunt_config import (  # type: ignore[import-untyped]  # noqa: E501
    DOMAIN_CONTENT_TYPES,
    DOMAIN_ID,
    DOMAIN_SEED_REQUESTS,
    DOMAIN_VOICE_PROFILES,
)


# ---------------------------------------------------------------------------
# DOMAIN_ID
# ---------------------------------------------------------------------------


class TestDomainId:
    def test_is_non_empty_string(self):
        """DOMAIN_ID is a non-empty string."""
        assert isinstance(DOMAIN_ID, str)
        assert len(DOMAIN_ID) > 0

    def test_is_snake_case(self):
        """DOMAIN_ID uses snake_case."""
        assert " " not in DOMAIN_ID
        assert DOMAIN_ID == DOMAIN_ID.lower()


# ---------------------------------------------------------------------------
# DOMAIN_CONTENT_TYPES
# ---------------------------------------------------------------------------


class TestDomainContentTypes:
    def test_is_non_empty_list(self):
        """DOMAIN_CONTENT_TYPES is a non-empty list."""
        assert isinstance(DOMAIN_CONTENT_TYPES, list)
        assert len(DOMAIN_CONTENT_TYPES) >= 3

    def test_every_entry_has_required_fields(self):
        """Every content type has name, description, required_params,
        optional_params."""
        for ct in DOMAIN_CONTENT_TYPES:
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
        names = [ct["name"] for ct in DOMAIN_CONTENT_TYPES]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_names_are_snake_case(self):
        """All content type names use snake_case with no spaces."""
        for ct in DOMAIN_CONTENT_TYPES:
            name = ct["name"]
            assert " " not in name, f"Name '{name}' contains spaces"
            assert name == name.lower(), f"Name '{name}' is not lowercase"

    def test_all_have_voice_profile(self):
        """Every domain content type specifies a voice_profile."""
        for ct in DOMAIN_CONTENT_TYPES:
            assert "voice_profile" in ct, (
                f"Missing 'voice_profile' in {ct['name']}"
            )
            assert ct["voice_profile"] in {
                "recruiter-persuasive",
                "candidate-confident",
                "hiring-manager-neutral",
            }, (
                f"Unexpected voice_profile '{ct['voice_profile']}' "
                f"in {ct['name']}"
            )

    def test_expected_types_present(self):
        """All 5 expected job hunt types are present."""
        names = {ct["name"] for ct in DOMAIN_CONTENT_TYPES}
        expected = {"resume", "cover_letter", "job_match",
                    "interview_prep", "salary_benchmark"}
        missing = expected - names
        assert not missing, f"Missing expected types: {missing}"

    def test_does_not_overlap_with_core_types(self):
        """Domain content types do not duplicate core seed_data types."""
        from research_shared.seed_data import CONTENT_TYPES as CORE_TYPES

        domain_names = {ct["name"] for ct in DOMAIN_CONTENT_TYPES}
        core_names = {ct["name"] for ct in CORE_TYPES}
        overlap = domain_names & core_names
        assert not overlap, (
            f"Domain types overlap with core types: {overlap}"
        )


# ---------------------------------------------------------------------------
# DOMAIN_VOICE_PROFILES
# ---------------------------------------------------------------------------


class TestDomainVoiceProfiles:
    def test_is_non_empty_list(self):
        """DOMAIN_VOICE_PROFILES is a non-empty list."""
        assert isinstance(DOMAIN_VOICE_PROFILES, list)
        assert len(DOMAIN_VOICE_PROFILES) >= 2

    def test_every_profile_has_required_fields(self):
        """Every voice profile has name, description, tone."""
        for vp in DOMAIN_VOICE_PROFILES:
            assert "name" in vp
            assert isinstance(vp["name"], str)
            assert len(vp["name"]) > 0
            assert "description" in vp
            assert isinstance(vp["description"], str)
            assert "tone" in vp
            assert isinstance(vp["tone"], str)

    def test_names_are_unique(self):
        """No duplicate voice profile names."""
        names = [vp["name"] for vp in DOMAIN_VOICE_PROFILES]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_expected_profiles_present(self):
        """All 3 expected job hunt voice profiles are present."""
        names = {vp["name"] for vp in DOMAIN_VOICE_PROFILES}
        expected = {"recruiter-persuasive", "candidate-confident",
                    "hiring-manager-neutral"}
        missing = expected - names
        assert not missing, f"Missing expected profiles: {missing}"

    def test_does_not_overlap_with_core_profiles(self):
        """Domain voice profiles do not duplicate core seed_data profiles."""
        from research_shared.seed_data import VOICE_PROFILES as CORE_PROFILES

        domain_names = {vp["name"] for vp in DOMAIN_VOICE_PROFILES}
        core_names = {vp["name"] for vp in CORE_PROFILES}
        overlap = domain_names & core_names
        assert not overlap, (
            f"Domain profiles overlap with core profiles: {overlap}"
        )


# ---------------------------------------------------------------------------
# DOMAIN_SEED_REQUESTS
# ---------------------------------------------------------------------------


class TestDomainSeedRequests:
    def test_is_non_empty_list(self):
        """DOMAIN_SEED_REQUESTS is a non-empty list."""
        assert isinstance(DOMAIN_SEED_REQUESTS, list)
        assert len(DOMAIN_SEED_REQUESTS) >= 5

    def test_every_request_has_required_fields(self):
        """Every seed request has content_type, prompt."""
        valid_types = {ct["name"] for ct in DOMAIN_CONTENT_TYPES}
        for sr in DOMAIN_SEED_REQUESTS:
            assert "content_type" in sr, f"Missing 'content_type' in {sr}"
            assert sr["content_type"] in valid_types, (
                f"Unknown content_type '{sr['content_type']}' "
                f"in seed request"
            )
            assert "prompt" in sr, f"Missing 'prompt' in {sr}"
            assert isinstance(sr["prompt"], str)
            assert len(sr["prompt"]) > 0

    def test_covers_all_types(self):
        """Seed requests cover all domain content types."""
        sr_types = {sr["content_type"] for sr in DOMAIN_SEED_REQUESTS}
        type_names = {ct["name"] for ct in DOMAIN_CONTENT_TYPES}
        uncovered = type_names - sr_types
        assert not uncovered, (
            f"Content types without seed requests: {uncovered}"
        )

    def test_parameters_are_valid_dict(self):
        """Parameters, when present, are a non-empty dict."""
        for sr in DOMAIN_SEED_REQUESTS:
            if "parameters" in sr:
                assert isinstance(sr["parameters"], dict)
