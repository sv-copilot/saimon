"""Primacy distance (#254).

The production stub returns 1.0 for everything, so every observation reads
`primary`. These tests pin the ported formula so that a constant cannot come back.
"""

from __future__ import annotations

import pytest

from research_shared.primacy import (
    MEDIATED_MARKERS,
    NO_PATH_LINEAGE_DISTANCE,
    PRIMACY_VERSION,
    compute_primacy,
    grounding_distance,
    lineage_distance,
    mediated_distance,
    source_class_from_host,
    source_distance,
    tier_for,
)


class TestSourceClass:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("arxiv.org", "journal_article"),
            ("www.nasa.gov", "government_report"),
            ("en.wikipedia.org", "report"),
            ("medium.com", "blog"),
            ("reddit.com", "forum_post"),
            ("reuters.com", "news"),
            ("some-random-site.example", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_hosts(self, host, expected):
        assert source_class_from_host(host) == expected

    def test_unknown_host_is_not_treated_as_direct(self):
        assert source_distance("unknown") > source_distance("journal_article")

    def test_journal_closer_than_blog(self):
        assert source_distance("journal_article") < source_distance("blog")


class TestMediatedLanguage:
    def test_marker_flag_adds_weight(self):
        plain = mediated_distance("Unemployment rose 4.2% in 2023")
        hedged = mediated_distance("According to the report, unemployment rose 4.2% in 2023")
        assert hedged > plain

    def test_every_marker_is_detected(self):
        for marker in MEDIATED_MARKERS:
            assert mediated_distance(f"{marker} the rate changed") > 0.0

    def test_bracket_citation_adds_weight(self):
        assert mediated_distance("The rate rose 4.2% [12]") > mediated_distance("The rate rose 4.2%")

    def test_bounded_at_one(self):
        text = "according to reporters, the summary of previous studies said the report notes [1]"
        assert mediated_distance(text, extraction_method="inference") <= 1.0


class TestGrounding:
    def test_supported_beats_insufficient(self):
        assert grounding_distance("supported", 0.9) < grounding_distance("insufficient_evidence")

    def test_high_confidence_supported_is_best(self):
        assert grounding_distance("supported", 1.0) < grounding_distance("supported", 0.2)

    def test_error_is_worst(self):
        assert grounding_distance("error") > grounding_distance("mixed")


class TestLineage:
    def test_hops_map_to_distance(self):
        assert lineage_distance(0)[0] == 0.0
        assert lineage_distance(3)[0] == pytest.approx(1.0)

    def test_no_path_uses_the_flat_penalty(self):
        assert lineage_distance(None)[0] == pytest.approx(NO_PATH_LINEAGE_DISTANCE)


class TestTiers:
    def test_direct_requires_a_hop_path(self):
        assert tier_for(0.1, 0) == "direct"
        assert tier_for(0.1, None) != "direct"

    def test_bands_without_hops(self):
        assert tier_for(0.30, None) == "near_direct"
        assert tier_for(0.60, None) == "mediated"
        assert tier_for(0.90, None) == "multi_hop"


class TestCompute:
    def test_primary_paper_claim_scores_low_distance(self):
        score, tier, breakdown = compute_primacy(
            text="HNSW recall improves as ef_search rises",
            source_class="journal_article", hops=1, verification_status="supported",
            confidence=0.9,
        )
        assert score is not None and score < 0.45
        assert tier == "near_direct"
        assert breakdown["version"] == PRIMACY_VERSION

    def test_hedged_blog_claim_scores_high_distance(self):
        score, tier, _ = compute_primacy(
            text="According to previous studies, the tool reportedly improves results [3]",
            source_class="blog", hops=None, verification_status="insufficient_evidence",
        )
        assert score is not None and score > 0.6
        assert tier in {"mediated", "multi_hop"}

    def test_distance_is_not_a_constant(self):
        """The stub returned 1.0 everywhere; a spread is the whole point."""
        scores = {
            compute_primacy(text="Direct measurement of 4.2%", source_class="dataset", hops=0,
                            verification_status="supported", confidence=0.9)[0],
            compute_primacy(text="According to the summary, it is believed to be high",
                            source_class="blog", hops=None,
                            verification_status="error")[0],
        }
        assert len(scores) == 2 and min(scores) < max(scores)

    def test_missing_context_reports_unknown_with_a_reason(self):
        score, tier, breakdown = compute_primacy(
            text="anything", source_class=None, hops=None, has_context=False
        )
        assert score is None and tier == "unknown"
        assert breakdown["reason"] == "missing_source_and_document_context"

    def test_breakdown_carries_every_component(self):
        _, _, breakdown = compute_primacy(
            text="x", source_class="report", hops=2, verification_status="mixed", confidence=0.5
        )
        for key in ("lineage_component", "mediated_language_component",
                    "source_provenance_component", "grounding_component", "source_class"):
            assert key in breakdown
