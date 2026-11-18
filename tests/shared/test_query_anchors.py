"""A question about a named thing is not answered by a passage about something else."""

from __future__ import annotations

from research_shared.rerank import anchors_missing, query_anchors, rerank


def test_proper_nouns_are_anchors() -> None:
    assert query_anchors("What did the Saimon audit say about the Redis cache?") == [
        "saimon", "redis"]


def test_question_starters_and_years_are_not() -> None:
    assert query_anchors("Who won the 2024 super bowl?") == []


def test_lowercase_subjects_are_not_anchors() -> None:
    # "sous vide" is a subject but the phrase is lowercase, so it is not an
    # anchor; the coverage gate handles it.
    assert query_anchors("How does sous vide cooking hold a temperature?") == []


def test_missing_subject_is_detected() -> None:
    assert anchors_missing("What about the Redis cache?", "A passage about memcached.") is True
    assert anchors_missing("What about the Redis cache?", "Redis keeps a cache.") is False


def test_gate_refuses_a_passage_that_never_names_the_subject() -> None:
    candidates = [{
        "id": "c1", "title": "Deployment pipeline", "body": "The pipeline caches build layers.",
        "similarity": 0.82,
    }]
    outcome = rerank("What did the Saimon audit find about the Redis cache?", candidates)
    assert outcome.fail_safe_fired is True
    assert outcome.abstain_reason == "missing_subject"


def test_gate_allows_a_passage_that_names_it() -> None:
    candidates = [{
        "id": "c2", "title": "Redis cache", "body": "Redis caches the session lookups.",
        "similarity": 0.82,
    }]
    outcome = rerank("What did the Saimon audit find about the Redis cache?", candidates)
    assert outcome.abstain_reason != "missing_subject"
