"""Consensus and contradiction views (#274)."""

from __future__ import annotations

from research_shared.consensus import (
    CONSENSUS,
    CONTESTED,
    CONTRADICTION,
    SILENT,
    build_view,
    summarise,
)


def rel(relation_type: str, id_: str, title: str = "t", weight: float = 0.9) -> dict:
    return {"target_id": id_, "title": title, "relation_type": relation_type,
            "weight": weight, "metadata": {"reason": "test"}}


class TestOutcomes:
    def test_no_relations_is_silent_not_empty(self):
        view = build_view("seed", [])
        assert view.outcome == SILENT
        assert view.as_dict()["counts"]["supporting"] == 0

    def test_supports_only_is_consensus(self):
        assert build_view("seed", [rel("supports", "a")]).outcome == CONSENSUS

    def test_contradicts_only_is_contradiction(self):
        assert build_view("seed", [rel("contradicts", "a")]).outcome == CONTRADICTION

    def test_both_sides_is_contested(self):
        view = build_view("seed", [rel("supports", "a"), rel("contradicts", "b")])
        assert view.outcome == CONTESTED
        assert len(view.supporting) == 1 and len(view.dissenting) == 1

    def test_unrelated_relations_do_not_count_as_agreement(self):
        view = build_view("seed", [rel("related", "a")])
        assert view.outcome == SILENT
        assert len(view.unresolved) == 1


class TestMembers:
    def test_member_carries_provenance(self):
        view = build_view("seed", [rel("supports", "a", "A claim", 0.87)])
        member = view.supporting[0]
        assert member["id"] == "a"
        assert member["strength"] == 0.87
        assert member["reason"] == "test"

    def test_as_dict_is_serialisable(self):
        payload = build_view("seed", [rel("supports", "a")]).as_dict()
        assert payload["seed_id"] == "seed"
        assert payload["counts"] == {"supporting": 1, "dissenting": 0, "unresolved": 0}


class TestSummarise:
    def test_aggregate_counts_and_contested_listing(self):
        views = [
            build_view("s1", [rel("supports", "a")]),
            build_view("s2", [rel("supports", "b"), rel("contradicts", "c")]),
            build_view("s3", []),
        ]
        report = summarise(views)
        assert report["claims_examined"] == 3
        assert report["outcomes"][CONSENSUS] == 1
        assert report["outcomes"][CONTESTED] == 1
        assert report["outcomes"][SILENT] == 1
        assert len(report["contested"]) == 1

    def test_silent_claims_are_named(self):
        report = summarise([build_view("s3", [])])
        assert report["silent_claims"] == ["s3"]
