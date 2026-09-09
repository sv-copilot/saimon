"""scaffold_claim.py — claim-elements scaffolder (SAIMON-LEGAL-CLAIM-SCAFFOLD-1).

The retail legal bridge from "is the law on our side" to "how good is our
position."  Given a claim type, a target jurisdiction, and the client's facts,
``scaffold_claim`` enumerates the claim's elements and, for each element:

- ranks the strongest authority using ``build_authority_ladder`` (which
  composes ``rank_persuasive_authority``) and reports confidence,
- flags a circuit split via ``detect_split_of_authority``,
- flags elements that are factually weak given the client's structured
  element checklist (with a free-text fallback).

Like the rest of the legal plugin, this is deterministic: the claim-element
enumeration comes from the curated claims catalog, and the authority
ranking/split detection compose the existing pure building blocks — no network
I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.claims import get_claim_type
from plugins.legal.tools.authority_ladder import build_authority_ladder
from plugins.legal.tools.split_of_authority import detect_split_of_authority

#: Fact values that indicate a checklist item is not established.
_WEAK_STRINGS = frozenset(
    {
        "",
        "0",
        "absent",
        "cannot prove",
        "false",
        "lacking",
        "missing",
        "no",
        "none",
        "not established",
        "unclear",
        "unestablished",
        "unknown",
        "unlikely",
        "unproven",
        "weak",
    }
)

_FREE_TEXT_WEAK_MARKERS = (
    "no evidence",
    "unable to prove",
    "cannot prove",
    "not established",
    "absent",
    "missing",
    "lacking",
    "weak",
)


def _is_weak_value(value: Any) -> bool:
    """Return True when *value* signals a fact is not established."""
    if value is None:
        return True
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    return str(value).strip().lower() in _WEAK_STRINGS


def _free_text_weakness(element: dict[str, Any], free_text: str) -> str | None:
    """Return a reason when free text flags *element* as weak, else None."""
    text = (free_text or "").lower()
    if not text or not any(marker in text for marker in _FREE_TEXT_WEAK_MARKERS):
        return None

    haystacks = [element.get("name", "")] + list(element.get("fact_keys", []))
    keywords: set[str] = set()
    for haystack in haystacks:
        keywords.update(
            word
            for word in str(haystack).replace("_", " ").lower().split()
            if len(word) > 2
        )
    if any(keyword in text for keyword in keywords):
        return f"free text flags weakness for '{element.get('name')}'"
    return None


def _weak_reasons(element: dict[str, Any], client_facts: dict[str, Any]) -> list[str]:
    """Compute weakness reasons for *element* from structured facts + free text."""
    facts = client_facts.get("facts") or {}
    reasons: list[str] = []
    for key in element.get("fact_keys", []):
        if key in facts and _is_weak_value(facts[key]):
            reasons.append(f"fact '{key}' is not established")

    free_text = str(client_facts.get("free_text") or "").strip()
    free_text_reason = _free_text_weakness(element, free_text)
    if free_text_reason:
        reasons.append(free_text_reason)
    return reasons


def _authority_summary(ladder: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract the strongest authority with confidence from a ladder."""
    if not ladder:
        return None
    top = ladder[0]
    if len(ladder) == 1:
        confidence = top["score"]
    else:
        confidence = max(0.0, min(1.0, top["score"] - ladder[1]["score"]))
    return {
        "citation": top["citation"],
        "score": top["score"],
        "confidence": round(confidence, 4),
        "reasoning": top["reasoning"],
    }


def scaffold_claim(
    claim_type: str,
    jurisdiction: str | None = None,
    client_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enumerate a claim's elements and scaffold each with authority + flags.

    Args:
        claim_type: A catalog key (``dtsa_misappropriation``, ``state_trade_secret``,
            ``cfaa``, ``tortious_interference``).
        jurisdiction: Target jurisdiction for authority ranking (default ``federal``).
        client_facts: Optional ``{"facts": {key: value}, "free_text": "..."}``.
            ``facts`` is a structured element checklist; ``free_text`` is a
            fallback for unstructured client input.

    Returns:
        An element-by-element scaffold with ranked authority, split flags,
        weakness flags, a verified/annotated memo, and a verification block.
    """
    entry = get_claim_type(claim_type)
    jurisdiction = (jurisdiction or "federal").strip() or "federal"
    client_facts = client_facts or {}

    scaffolds: list[dict[str, Any]] = []
    for element in entry["elements"]:
        name = element["name"]
        authorities = element.get("authorities", [])
        context: dict[str, Any] = {
            "target_jurisdiction": jurisdiction,
            "issue": name,
        }
        ladder_result = build_authority_ladder(authorities, context)
        ladder = ladder_result["ladder"]
        split_result = detect_split_of_authority(authorities)
        weak_reasons = _weak_reasons(element, client_facts)

        scaffolds.append(
            {
                "element": name,
                "description": element.get("description", ""),
                "authority": _authority_summary(ladder),
                "ladder": ladder,
                "split": split_result["split"],
                "split_summary": split_result["summary"],
                "weak": bool(weak_reasons),
                "weak_reasons": weak_reasons,
            }
        )

    weak_elements = [s["element"] for s in scaffolds if s["weak"]]
    split_elements = [s["element"] for s in scaffolds if s["split"]]

    memo_lines = [
        (
            f"{entry['name']} scaffold ({len(scaffolds)} elements) "
            f"in {jurisdiction} jurisdiction."
        )
    ]
    for s in scaffolds:
        authority = s["authority"]
        if authority:
            authority_text = (
                f"{authority['citation']} (score {authority['score']:.2f}, "
                f"confidence {authority['confidence']:.2f})"
            )
        else:
            authority_text = "no recorded authority"
        flags = []
        if s["split"]:
            flags.append("split")
        if s["weak"]:
            flags.append("weak")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        memo_lines.append(f"- {s['element']}: {authority_text}{flag_text}")
    memo = "\n".join(memo_lines) + "\n"

    annotations = [
        {
            "element": s["element"],
            "authority": (s["authority"] or {}).get("citation"),
            "split": s["split"],
            "weak": s["weak"],
        }
        for s in scaffolds
    ]

    return {
        "claim_type": claim_type,
        "claim_name": entry["name"],
        "jurisdiction": jurisdiction,
        "element_count": len(scaffolds),
        "elements": scaffolds,
        "weak_elements": weak_elements,
        "split_elements": split_elements,
        "verification": {
            "verified": True,
            "method": (
                "deterministic claim-scaffold annotation over ranked authority, "
                "circuit split, and weakness flags"
            ),
            "weak_elements": weak_elements,
            "split_elements": split_elements,
            "annotations": annotations,
        },
        "memo": memo,
    }


class ScaffoldClaimTool:
    """DomainTool wrapper for :func:`scaffold_claim`."""

    name = "legal.scaffold_claim"
    description = (
        "Enumerate a legal claim's elements and scaffold each with the "
        "strongest ranked authority (plus confidence), a circuit-split flag, "
        "and a factual-weakness flag against the client's facts."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "claim_type": {"type": "string"},
            "jurisdiction": {"type": "string"},
            "client_facts": {"type": "object"},
        },
        "required": ["claim_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        claim_type = arguments.get("claim_type")
        if not claim_type:
            raise ValueError("Parameter 'claim_type' is required.")
        jurisdiction = arguments.get("jurisdiction")
        client_facts = arguments.get("client_facts") or {}
        if not isinstance(client_facts, dict):
            raise TypeError("Parameter 'client_facts' must be an object.")
        return scaffold_claim(str(claim_type), jurisdiction, client_facts)

