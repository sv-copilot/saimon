"""test_content_profiles.py — fixture tests for #45 SAIMON-CONTENT-PROFILES.

Tests per-type system prompts, banlists, form factors, quality gate
enforcement, and form-factor-aware scoring.
"""

import pytest
from research_shared.seed_data import CONTENT_TYPES


# ── Profile completeness tests ────────────────────────────────────────

class TestContentTypeProfiles:
    """Verify all content types have the required profile fields."""

    def test_all_types_have_document_family(self):
        for ct in CONTENT_TYPES:
            assert "document_family" in ct, (
                f"{ct['name']} missing document_family"
            )
            assert ct["document_family"] in (
                "long_form", "marketing", "correspondence", "general",
                "job_application",
            ), f"{ct['name']}: unknown document_family '{ct['document_family']}'"

    def test_all_types_have_form_factor(self):
        for ct in CONTENT_TYPES:
            assert "form_factor" in ct, (
                f"{ct['name']} missing form_factor"
            )
            assert ct["form_factor"] in (
                "bullet", "short_paragraph", "paragraph", "section", "passage",
            ), f"{ct['name']}: unknown form_factor '{ct['form_factor']}'"

    def test_all_types_have_profile_key(self):
        for ct in CONTENT_TYPES:
            assert "profile_key" in ct, (
                f"{ct['name']} missing profile_key"
            )
            assert ct["profile_key"] in (
                "long_form", "marketing", "correspondence", "general",
                "job_application",
            ), f"{ct['name']}: unknown profile_key '{ct['profile_key']}'"

    def test_blog_post_has_system_prompt(self):
        blog = next(ct for ct in CONTENT_TYPES if ct["name"] == "blog_post")
        assert "system_prompt" in blog
        assert len(blog.get("system_prompt", "")) > 20
        assert len(blog.get("banlist", [])) > 0
        assert blog.get("form_factor") == "section"

    def test_social_post_has_system_prompt(self):
        social = next(ct for ct in CONTENT_TYPES if ct["name"] == "social_post")
        assert "system_prompt" in social
        assert len(social.get("system_prompt", "")) > 20
        assert len(social.get("banlist", [])) > 0
        assert social.get("form_factor") == "short_paragraph"

    def test_meeting_notes_is_bullet(self):
        notes = next(ct for ct in CONTENT_TYPES if ct["name"] == "meeting_notes")
        assert notes.get("form_factor") == "bullet"

    def test_bibliography_is_bullet(self):
        bib = next(ct for ct in CONTENT_TYPES if ct["name"] == "bibliography")
        assert bib.get("form_factor") == "bullet"

    def test_per_type_prompts_differ(self):
        blog = next(ct for ct in CONTENT_TYPES if ct["name"] == "blog_post")
        social = next(ct for ct in CONTENT_TYPES if ct["name"] == "social_post")
        assert blog["system_prompt"] != social["system_prompt"]

    def test_banlists_are_nonempty_for_most_types(self):
        """Most content types should have non-empty banlists."""
        empty_banlists = [
            ct["name"] for ct in CONTENT_TYPES
            if len(ct.get("banlist", [])) == 0
        ]
        # Allow a few types to have empty banlists (e.g., summary)
        assert len(empty_banlists) <= 2, (
            f"Too many types with empty banlists: {empty_banlists}"
        )


# ── Form factor resolution tests ──────────────────────────────────────

class TestFormFactorResolution:
    def test_blog_post_form_factor(self):
        from mcp.evaluate.server import _resolve_form_factor
        assert _resolve_form_factor("blog_post") == "section"

    def test_social_post_form_factor(self):
        from mcp.evaluate.server import _resolve_form_factor
        assert _resolve_form_factor("social_post") == "short_paragraph"

    def test_unknown_type_defaults_to_passage(self):
        from mcp.evaluate.server import _resolve_form_factor
        assert _resolve_form_factor("nonexistent_type") == "passage"

    def test_none_defaults_to_passage(self):
        from mcp.evaluate.server import _resolve_form_factor
        assert _resolve_form_factor(None) == "passage"

    def test_bullet_type_resolved(self):
        from mcp.evaluate.server import _resolve_form_factor
        assert _resolve_form_factor("meeting_notes") == "bullet"


# ── Per-type prompt generation tests ──────────────────────────────────

class TestTypePrompt:
    def test_blog_post_prompt_includes_system_prompt(self):
        from mcp.generate.server import _get_type_prompt
        result = _get_type_prompt(
            "blog_post", "test prompt", "analytical", ""
        )
        assert "blog author" in result.lower()
        assert "blog_post" not in result.lower()  # underscores replaced
        assert "Do not invent statistics" in result

    def test_social_post_prompt_differs(self):
        from mcp.generate.server import _get_type_prompt
        result = _get_type_prompt(
            "social_post", "test prompt", "casual", ""
        )
        assert "social media writer" in result.lower()
        # Should not contain blog author language
        assert "blog author" not in result.lower()

    def test_banlist_included_in_prompt(self):
        from mcp.generate.server import _get_type_prompt
        result = _get_type_prompt(
            "press_release", "test", "formal", ""
        )
        # Press release banlist should include "game-changer"
        assert "game-changer" in result.lower()

    def test_unknown_type_uses_generic_template(self):
        from mcp.generate.server import _get_type_prompt
        result = _get_type_prompt(
            "nonexistent_type", "test", "neutral", ""
        )
        assert "content generation assistant" in result.lower()


# ── Quality gate tests ────────────────────────────────────────────────

class TestQualityGate:
    def test_banlist_phrase_rejected(self):
        """Verify banlisted phrases trigger quality gate failure."""
        from mcp.generate.server import _quality_gate_check
        from research_shared.seed_data import CONTENT_TYPES
        # blog_post banlist includes "delve into"
        result = _quality_gate_check(
            "Let us delve into this topic more deeply.",
            "blog_post",
        )
        assert result["passed"] is False
        assert "delve" in result["reason"].lower()

    def test_clean_content_passes(self):
        from mcp.generate.server import _quality_gate_check
        result = _quality_gate_check(
            "This is a clean paragraph about climate science.",
            "blog_post",
        )
        assert result["passed"] is True

    def test_ai_self_reference_rejected(self):
        from mcp.generate.server import _quality_gate_check
        result = _quality_gate_check(
            "As an AI language model, I can help with that.",
            "blog_post",
        )
        assert result["passed"] is False

    def test_job_posting_banlist_rejects_rockstar(self):
        from mcp.generate.server import _quality_gate_check
        result = _quality_gate_check(
            "We are looking for a rockstar developer.",
            "job_posting",
        )
        assert result["passed"] is False
        assert "rockstar" in result["reason"].lower()


# ── Form-factor-aware AI detection tests ──────────────────────────────

class TestFormFactorAwareAI:
    def test_bullet_content_gets_penalized_less(self):
        """Bullet form factor should allow higher bullet ratio."""
        from mcp.evaluate.server import _score_ai_detection
        bullet_text = "\n".join([f"- Point {i}" for i in range(10)])
        result_bullet = _score_ai_detection(
            bullet_text, content_type="meeting_notes",
        )
        result_default = _score_ai_detection(
            bullet_text, content_type=None,
        )
        # Bullet content should score HIGHER (less penalized)
        assert result_bullet["score"] >= result_default["score"], (
            f"Bullet ({result_bullet['score']:.2f}) should >= "
            f"default ({result_default['score']:.2f})"
        )

    def test_section_content_gets_default_thresholds(self):
        from mcp.evaluate.server import _score_ai_detection
        text = "This is a normal paragraph about technology trends."
        result = _score_ai_detection(text, content_type="blog_post")
        assert 0.0 <= result["score"] <= 1.0
        assert "AI detection" in result["justification"]

    def test_empty_content_neutral(self):
        from mcp.evaluate.server import _score_ai_detection
        result = _score_ai_detection("", content_type="blog_post")
        assert result["score"] == 0.5

    def test_all_types_have_valid_form_factor_scoring(self):
        """Verify _score_ai_detection doesn't crash for any content type."""
        from mcp.evaluate.server import _score_ai_detection
        for ct in CONTENT_TYPES:
            result = _score_ai_detection(
                "Test content for scoring.", content_type=ct["name"],
            )
            assert 0.0 <= result["score"] <= 1.0, (
                f"{ct['name']}: score {result['score']} out of range"
            )
