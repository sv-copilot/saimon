"""erie_guess.py — Erie prediction tool (legal tool 8/10, #75).

Composes search + verify + weighting: predict how a federal diversity court
will rule on unsettled state law by scoring each candidate state's evidence
under the #71 persuasive-authority model.  Deterministic — no network I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.weighting import persuasive_authority


def _citation_of(case: dict[str, Any]) -> str:
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}
    return (
        meta.get("citation_string")
        or case.get("title")
        or case.get("id")
        or "unnamed case"
    )


def _mean_persuasive(evidence: list[dict[str, Any]], context: dict[str, Any]) -> float:
    if not evidence:
        return 0.5
    scores = [persuasive_authority(case, context) for case in evidence]
    return sum(scores) / len(scores)


def predict_erie_guess(
    question: str,
    candidates: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Predict which state's law a diversity court will apply under Erie.

    Each candidate is scored by the mean persuasive authority of its evidence
    cases; the highest-scoring candidate is the prediction.  Confidence is the
    score margin over the runner-up (or the winning score when there is no
    runner-up).
    """
    ctx = context or {}
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        state = str(candidate.get("state") or candidate.get("name") or "unnamed")
        evidence = candidate.get("evidence") or []
        score = _mean_persuasive(evidence, ctx)
        scored.append(
            {
                "state": state,
                "score": score,
                "evidence": [_citation_of(case) for case in evidence],
            }
        )

    ordered = sorted(scored, key=lambda item: item["score"], reverse=True)
    if not ordered:
        return {
            "question": question,
            "prediction": None,
            "confidence": 0.0,
            "evidence": [],
            "scores": {},
            "memo": "No candidate states to predict from.",
        }

    top = ordered[0]
    if len(ordered) == 1:
        confidence = top["score"]
    else:
        confidence = max(0.0, min(1.0, top["score"] - ordered[1]["score"]))

    memo = f"Predicted governing law: {top['state']} (confidence {confidence:.4f})."
    return {
        "question": question,
        "prediction": top["state"],
        "confidence": round(confidence, 4),
        "evidence": top["evidence"],
        "scores": {s["state"]: round(s["score"], 4) for s in scored},
        "memo": memo,
    }


class PredictErieGuessTool:
    """DomainTool wrapper for :func:`predict_erie_guess`."""

    name = "legal.predict_erie_guess"
    description = (
        "Predict which state's law a diversity court will apply under Erie, "
        "returning the prediction, confidence, and supporting evidence."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "candidates": {"type": "array", "items": {"type": "object"}},
            "context": {"type": "object"},
        },
        "required": ["question", "candidates"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        question = arguments.get("question")
        if not question:
            raise ValueError("Parameter 'question' is required.")
        candidates = arguments.get("candidates")
        if not isinstance(candidates, list):
            raise TypeError("Parameter 'candidates' must be a list.")
        context = arguments.get("context") or {}
        if not isinstance(context, dict):
            raise TypeError("Parameter 'context' must be an object.")
        return predict_erie_guess(str(question), candidates, context)
