"""content_types.py — legal content types for the content_type_registry."""

from __future__ import annotations

from typing import Any

CONTENT_TYPES: list[dict[str, Any]] = [
    {
        "name": "legal:case",
        "description": "A judicial opinion or decided case with citation metadata.",
        "required_params": [
            {
                "name": "citation_string",
                "type": "str",
                "description": "Canonical citation (e.g. '410 U.S. 113').",
            }
        ],
        "optional_params": [
            {"name": "court", "type": "str", "description": "Deciding court."},
            {
                "name": "jurisdiction",
                "type": "str",
                "description": "Jurisdiction of the court.",
            },
        ],
        "voice_profile": "spencer-default",
    },
    {
        "name": "legal:brief_extract",
        "description": "An extract from a filed brief or docket document.",
        "required_params": [
            {
                "name": "prompt",
                "type": "str",
                "description": "The brief text or document to extract.",
            }
        ],
        "optional_params": [],
        "voice_profile": "spencer-default",
    },
    {
        "name": "legal:research_memo",
        "description": "A legal research memorandum.",
        "required_params": [
            {
                "name": "prompt",
                "type": "str",
                "description": "The research question.",
            }
        ],
        "optional_params": [],
        "voice_profile": "spencer-default",
    },
    {
        "name": "legal:erie_guess",
        "description": "A prediction of which state's law governs under Erie.",
        "required_params": [
            {
                "name": "prompt",
                "type": "str",
                "description": "The choice-of-law question.",
            }
        ],
        "optional_params": [],
        "voice_profile": "spencer-default",
    },
    {
        "name": "legal:split_inventory",
        "description": "An inventory of circuit splits on a legal question.",
        "required_params": [
            {
                "name": "prompt",
                "type": "str",
                "description": "The legal question to inventory.",
            }
        ],
        "optional_params": [],
        "voice_profile": "spencer-default",
    },
    {
        "name": "legal:claim_scaffold",
        "description": (
            "An element-by-element scaffold of a legal claim with ranked "
            "authority, circuit-split flags, and factual-weakness flags."
        ),
        "required_params": [
            {
                "name": "claim_type",
                "type": "str",
                "description": (
                    "Claim type key (e.g. 'dtsa_misappropriation', "
                    "'state_trade_secret', 'cfaa', 'tortious_interference')."
                ),
            },
            {
                "name": "jurisdiction",
                "type": "str",
                "description": "Target jurisdiction for authority ranking.",
            },
        ],
        "optional_params": [
            {
                "name": "client_facts",
                "type": "dict",
                "description": (
                    "Structured element checklist ('facts') plus an optional "
                    "'free_text' fallback field."
                ),
            }
        ],
        "voice_profile": "spencer-default",
    },
]
