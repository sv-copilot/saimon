"""A passage that never names the claim's subject is not evidence either way.

The verifier labelled unrelated passages `supports` (generic word overlap) or,
when the claim was negated, `contradicts` (the same overlap, inverted). Both
produce a confident verdict from a document about something else.
"""

from __future__ import annotations

import pytest

from research_shared.evidence import (
    anchor_terms,
    classify_stance,
    collect_corpus_evidence,
    subject_missing,
)

SHAPE_UP = (
    "Write the pitch. Shape Up chapters argue that a fixed time box and a variable "
    "scope beat an estimate, because product teams cannot predict how long "
    "discovery will take."
)

TOOL_LLM = (
    "ToolLLM: Facilitating LLMs to Master 16000+ Real-world APIs. In our initial "
    "investigations, we surprisingly found that even human experts often disagree."
)

EDMONDSON = (
    "Edmondson (1999) found that psychological safety predicts learning behavior in "
    "work teams: teams that shared errors improved, while teams that hid them did not."
)

GRAPHRAG = (
    "GraphRAG: from local to global. The approach summarises a graph of entities and "
    "answers query-focused questions over the whole corpus."
)


def test_proper_noun_anchor_is_extracted() -> None:
    assert anchor_terms("Janis wasn't writing about product teams.") == ["janis"]


def test_year_is_an_anchor() -> None:
    assert "1974" in anchor_terms("Tversky and Kahneman (1974) showed anchoring.")


def test_anchorless_claim_falls_back_to_long_words() -> None:
    assert anchor_terms("psychological safety predicts learning") == ["psychological"]


@pytest.mark.parametrize(
    "claim,passage",
    [
        ("Janis wasn't writing about product teams.", SHAPE_UP),
        ("Tversky and Kahneman (1974) showed that an initial number anchors later judgments.", GRAPHRAG),
        ("Edmondson found that psychological safety predicts learning behavior in work teams.", TOOL_LLM),
    ],
)
def test_unrelated_passage_is_never_support_or_contradiction(claim: str, passage: str) -> None:
    assert subject_missing(claim, passage) is True
    assert classify_stance(claim, passage) == "mentions"


def test_relevant_passage_still_supports() -> None:
    claim = "Edmondson found that psychological safety predicts learning behavior in work teams."
    assert subject_missing(claim, EDMONDSON) is False
    assert classify_stance(claim, EDMONDSON) == "supports"


@pytest.mark.asyncio
async def test_negated_claim_about_the_same_subject_still_contradicts() -> None:
    # Inversion happens in the collector, not in classify_stance: a negated
    # claim plus a passage asserting the positive is a contradiction.
    class _DB:
        async def fetch(self, sql, *args):
            return [{"id": "00000000-0000-4000-8000-00000000000a",
                     "title": "Janis, Victims of Groupthink",
                     "body": ("Janis wrote about small-group decision making at length and "
                              "coined the term groupthink to describe it."),
                     "content_type": "fulltext_chunk", "doi": ""}]

    items = await collect_corpus_evidence(
        _DB(), "Janis did not write about small-group decision making.")
    assert items and items[0]["polarity"] == "contradicts"


def test_anchorless_claim_is_not_gated() -> None:
    assert subject_missing("", "anything") is False


BIBLIOGRAPHY = (
    "Knowledge graphs matter for retrieval. References: Tversky, A., & Kahneman, D. "
    "(1974). Judgment under uncertainty: heuristics and biases. Science, 185(4157), "
    "1124-1131."
)


@pytest.mark.asyncio
async def test_bibliography_line_is_not_support() -> None:
    # A reference entry names the author and the year and asserts nothing.
    class _DB:
        async def fetch(self, sql, *args):
            return [{"id": "00000000-0000-4000-8000-00000000000b",
                     "title": "Knowledge Graphs (Hogan et al.)",
                     "body": BIBLIOGRAPHY, "content_type": "fulltext_chunk", "doi": ""}]

    items = await collect_corpus_evidence(
        _DB(), "Tversky and Kahneman (1974) showed that an initial number anchors later judgments.")
    assert items == []


def test_year_alone_does_not_satisfy_the_subject() -> None:
    claim = "Tversky and Kahneman (1974) showed that an initial number anchors later judgments."
    passage = "Minsky (1974) introduced frames as a way to represent stereotyped situations."
    assert subject_missing(claim, passage) is True
    assert classify_stance(claim, passage) == "mentions"


@pytest.mark.asyncio
async def test_document_path_can_carry_the_subject() -> None:
    class _DB:
        async def fetch(self, sql, *args):
            return [{"id": "00000000-0000-4000-8000-00000000000c",
                     "title": "Slice lifecycle state model",
                     "body": ("This document defines the canonical lifecycle states for slices "
                              "tracked in the planning tree, and the states they move through."),
                     "content_type": "source_document", "doi": "",
                     "path": "drake-governance/.docs/slice_lifecycle_state_model.md"}]

    items = await collect_corpus_evidence(_DB(), "Drake has lifecycle states for slices.")
    assert items and items[0]["polarity"] == "supports"


def test_evidence_sql_can_find_a_subject_by_path() -> None:
    from research_shared.evidence import EVIDENCE_SQL

    assert "metadata->>'path'" in EVIDENCE_SQL, (
        "a governance document need not repeat the product name in its body; "
        "without the path predicate it is unreachable by subject")


TABLE_CHUNK = """## Canonical states

| State | Meaning |
| --- | --- |
| `proposed` | Idea captured, no detail |
| `shaped` | Requirements documented |
| `ready` | Dependencies met |
| `archived` | Cancelled or blocked |
"""


def test_table_rows_are_scored_as_one_statement() -> None:
    from research_shared.evidence import best_sentence, support_score

    claim = "Drake has lifecycle states, from proposed to archived."
    sentence = best_sentence(TABLE_CHUNK, claim)
    assert support_score(claim, sentence) >= 2, sentence
