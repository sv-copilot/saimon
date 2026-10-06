"""Shared fixtures for proxy pipeline tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-proxy-key"


@pytest.fixture
def sample_prompt() -> str:
    return "Explain quantum entanglement in simple terms."


@pytest.fixture
def mock_generated_content() -> str:
    return (
        "Quantum entanglement is a phenomenon where two particles become "
        "correlated such that the state of one instantly influences the "
        "state of the other, regardless of distance. Albert Einstein "
        "famously called this 'spooky action at a distance' in 1935. "
        "The phenomenon was experimentally confirmed by Alain Aspect "
        "in 1982 at the University of Paris. Today, entanglement is "
        "a key resource for quantum computing and quantum cryptography."
    )


@pytest.fixture
def mock_extracted_claims() -> list[dict[str, object]]:
    return [
        {
            "claim_text": "Albert Einstein famously called this 'spooky action at a distance' in 1935.",
            "topic": "Einstein quote",
            "confidence_0_1": 0.95,
            "rationale": "Verifiable historical quote with specific date.",
        },
        {
            "claim_text": "Alain Aspect in 1982 at the University of Paris.",
            "topic": "Aspect experiment",
            "confidence_0_1": 0.92,
            "rationale": "Verifiable experimental result with specific date and location.",
        },
        {
            "claim_text": "entanglement is a key resource for quantum computing",
            "topic": "quantum computing",
            "confidence_0_1": 0.85,
            "rationale": "Verifiable against current scientific consensus.",
        },
    ]


@pytest.fixture
def mock_verify_supported() -> dict[str, object]:
    """Mock verify_claim response: supported."""
    return {
        "status": "success",
        "data": {
            "verifications": [
                {
                    "method": "source_corroboration",
                    "verdict": "supported",
                    "confidence": 0.88,
                    "explanation": "Multiple sources confirm this claim.",
                }
            ],
            "overall_verdict": "supported",
            "overall_confidence": 0.88,
            "methods_used": 1,
            "abstained": False,
        },
    }


@pytest.fixture
def mock_verify_refuted() -> dict[str, object]:
    """Mock verify_claim response: refuted."""
    return {
        "status": "success",
        "data": {
            "verifications": [
                {
                    "method": "authority_check",
                    "verdict": "refuted",
                    "confidence": 0.72,
                    "explanation": "Sources contradict this claim.",
                }
            ],
            "overall_verdict": "refuted",
            "overall_confidence": 0.72,
            "methods_used": 1,
            "abstained": False,
        },
    }


@pytest.fixture
def mock_evaluate_ai_detection() -> dict[str, object]:
    """Mock evaluate_content response with ai_detection."""
    return {
        "status": "success",
        "data": {
            "scores": [
                {
                    "criterion": "ai_detection",
                    "score": 0.65,
                    "justification": "Some formulaic patterns detected.",
                }
            ],
            "overall_score": 0.65,
        },
    }


@pytest.fixture
def mock_search_results() -> dict[str, object]:
    """Mock saimon_search_scholarly response with 2 academic papers."""
    return {
        "status": "success",
        "data": {
            "query": "quantum entanglement",
            "total_results": 2,
            "results": [
                {
                    "type": "academic_paper",
                    "identifier": "doi:10.1234/qe.2024",
                    "doi": "10.1234/qe.2024",
                    "title": "Quantum Entanglement: A Survey",
                    "authors": ["Bell, John"],
                    "year": 2024,
                    "relevance_score": 0.95,
                    "source_index": "alpha_index",
                },
                {
                    "type": "academic_paper",
                    "identifier": "doi:10.5678/qc.2023",
                    "doi": "10.5678/qc.2023",
                    "title": "Entanglement in Quantum Computing",
                    "authors": ["Preskill, John"],
                    "year": 2023,
                    "relevance_score": 0.88,
                    "source_index": "beta_index",
                },
            ],
        },
    }


@pytest.fixture
def mock_search_empty() -> dict[str, object]:
    """Mock saimon_search_scholarly response: no results."""
    return {
        "status": "success",
        "data": {
            "query": "nonexistent topic xyz",
            "total_results": 0,
            "results": [],
        },
    }
