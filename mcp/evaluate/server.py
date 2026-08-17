"""server.py — evaluate-mcp FastAPI application.

Provides quality-gate evaluation over generated content.  Scores
content against criteria (clarity, completeness, coherence,
conciseness, tone_match) and returns an overall quality score.

Supports LLM injection via set_llm_client() for AI-powered scoring.
Without an LLM, falls back to heuristic-based scoring.
"""

from __future__ import annotations

import json as _json
import logging as _logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from mcp.evaluate.writing_style import evaluate_voice
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.llm import LLMClient, LLMError
from research_shared.seed_data import CONTENT_TYPES as SEED_CONTENT_TYPES

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Inject an LLMClient for AI-powered evaluation scoring."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan(
    "evaluate-mcp", llm_client_ref=lambda: _llm_client, llm_client_setter=set_llm_client
)
app = FastAPI(title="evaluate-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# auth (fail-closed)
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)
apply_hardening(app, _auth)


def _require_auth(request: Request) -> None:
    """Fail-closed auth guard.  Called as a FastAPI dependency."""
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------

# criteria registry
# ---------------------------------------------------------------------------

_CRITERIA: dict[str, dict[str, Any]] = {
    "clarity": {
        "name": "clarity",
        "description": "How clear and readable the writing is.",
        "weight": 0.25,
    },
    "completeness": {
        "name": "completeness",
        "description": "How thoroughly the content covers the request.",
        "weight": 0.25,
    },
    "coherence": {
        "name": "coherence",
        "description": "How logically the content flows and connects.",
        "weight": 0.20,
    },
    "conciseness": {
        "name": "conciseness",
        "description": "How appropriately brief and to-the-point the content is.",
        "weight": 0.15,
    },
    "tone_match": {
        "name": "tone_match",
        "description": "How well the tone aligns with the requested tone.",
        "weight": 0.15,
    },
    "ai_detection": {
        "name": "ai_detection",
        "description": (
            "⚠️ DETERMINISTIC HEURISTIC ONLY — NOT an ML classifier. "
            "How likely the content was written by a human (1.0) vs AI-generated (0.0). "
            "Uses 12 pattern-matching checks (template phrases, burstiness, "
            "lexical diversity, sentence variance, punctuation diversity, "
            "personal stance regex, corporate neutrality, starter diversity, etc.). "
            "LIMITATIONS: cannot detect sophisticated AI output, may produce "
            "false positives on formal human writing. Do NOT use as sole "
            "evidence of AI generation."
        ),
        "weight": 1 / 6,
    },
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    import logging as _logging

    _log = _logging.getLogger("saimon.health")
    llm_ok = False
    if _llm_client is not None:
        try:
            await _llm_client.health_check()
            llm_ok = True
        except Exception:  # noqa: BLE001
            _log.debug("evaluate-mcp health: LLM not reachable", exc_info=True)
    return {
        "status": "ok",
        "service": "evaluate-mcp",
        "checks": {"llm": "connected" if llm_ok else "unavailable"},
    }


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "evaluate_content",
        "description": (
            "Score content against quality criteria (clarity, completeness, "
            "coherence, conciseness, tone_match, ai_detection). "
            "⚠️ ai_detection is a deterministic heuristic — NOT an ML "
            "classifier. Do not rely on it as sole evidence of AI generation."
        ),
        "parameters": {
            "content": "str (required)",
            "criteria": "list[str] (optional, defaults to all)",
            "tone": "str (optional, for tone_match criterion)",
        },
    },
    {
        "name": "list_criteria",
        "description": "List all evaluation criteria with descriptions and weights.",
        "parameters": {},
    },
    {
        "name": "get_criterion_detail",
        "description": "Get the schema for a specific evaluation criterion.",
        "parameters": {"criterion_name": "str (required)"},
    },
    {
        "name": "evaluate_voice",
        "description": (
            "Score a scene's style/voice consistency against per-character "
            "or POV voice profiles, with drift findings."
        ),
        "parameters": {
            "scene_text": "str (required)",
            "voice_profiles": "list[dict] (required)",
        },
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ok(
    trace_id: str,
    data: Any = None,
    citations: list[str] | None = None,
) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="success",
        data=data,
        citations=citations,
    )


def _degraded(trace_id: str, data: Any = None) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="degraded",
        data=data,
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# scoring engine
# ---------------------------------------------------------------------------

# ── content type lookup (for form factor resolution) ──────────────

_CONTENT_TYPES: dict[str, dict[str, Any]] = {
    ct["name"]: ct for ct in SEED_CONTENT_TYPES
}


def _resolve_form_factor(content_type: str | None) -> str:
    """Return the form_factor for a content type.

    Ported from legacy content_generation_voice_rubric.py:48-56.
    Valid values: bullet, short_paragraph, paragraph, section, passage.
    Defaults to 'passage' for unknown or unset types.
    """
    if not content_type:
        return "passage"
    ct = _CONTENT_TYPES.get(content_type, {})
    return ct.get("form_factor", "passage")


# ── scoring prompts and heuristics ─────────────────────────────────

_EVAL_PROMPT = """You are a content quality evaluator. Score the following content
against these criteria: {criteria}.

Content: {content}
Tone requested: {tone}

Return ONLY a JSON object with keys:
- "scores": array of {{ "criterion": "...", "score": 0.0-1.0, "justification": "..." }}
- "overall_score": weighted average (0.0-1.0)"""


async def _llm_evaluate(
    criteria_names: list[str], content: str, tone: str | None
) -> list[dict[str, Any]]:
    """Evaluate content via the injected LLM."""
    prompt = _EVAL_PROMPT.format(
        criteria=", ".join(criteria_names),
        content=content[:3000],
        tone=tone or "neutral",
    )
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    try:
        result = _json.loads(raw)
    except _json.JSONDecodeError:
        return []  # LLM returned malformed JSON — degrade gracefully
    if not isinstance(result, dict):
        return []  # LLM returned non-object JSON — degrade gracefully
    scores = result.get("scores")
    if not scores or not isinstance(scores, list):
        return []  # LLM returned null/missing scores — degrade gracefully
    return scores


import re as _re
from collections import Counter as _Counter
from statistics import mean as _mean
from statistics import stdev as _stdev


def _score_ai_detection(
    content: str,
    _tone: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Score content for AI-generated fingerprints using deterministic heuristics.

    Returns 0.0 (definitely AI) to 1.0 (passes as human).
    """
    if not content or not content.strip():
        return {
            "criterion": "ai_detection",
            "score": 0.5,
            "max_score": 1.0,
            "justification": "Empty content — neutral score.",
        }

    words = content.split()
    word_count = len(words)
    sentences = _re.split(r"[.!?]+", content)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = max(1, len(sentences))

    lines = content.split("\n")
    paragraphs = [l.strip() for l in lines if l.strip()]
    para_count = max(1, len(paragraphs))

    # ---- Check 1: Template phrases ----
    _TEMPLATE_PHRASES = [
        "delve into",
        "it's worth noting",
        "moreover",
        "furthermore",
        "thus",
        "in conclusion",
        "as an AI",
        "it is important to note",
        "crucial to understand",
        "plays a pivotal role",
        # Modern DeepSeek / GPT-4 era phrases
        "it is worth noting that",
        "it should be noted that",
        "it is essential to",
        "it is crucial to",
        "it is imperative that",
        "a testament to",
        "in the realm of",
        "in the context of",
        "it is widely acknowledged",
        "it is generally accepted",
        "a compelling case",
        "a nuanced understanding",
        "not only ... but also",
        "striking the right balance",
        "in an era of",
        "in today's rapidly evolving",
        "a delicate balance",
        "a double-edged sword",
        "a paradigm shift",
        "at the forefront of",
        "it is no exaggeration",
        "it goes without saying",
    ]
    content_lower = content.lower()
    template_hits = sum(1 for phrase in _TEMPLATE_PHRASES if phrase in content_lower)
    check1 = max(0.0, 1.0 - (template_hits / sentence_count) * 2)

    # ---- Check 2: Over-hedging ----
    hedge_on_one_hand = content_lower.count("on one hand")
    hedge_on_other = content_lower.count("on the other hand")
    hedge_pairs = min(hedge_on_one_hand, hedge_on_other)
    hedge_however = content_lower.count("however")
    hedge_nevertheless = content_lower.count("nevertheless")
    hedge_total = hedge_pairs + hedge_however + hedge_nevertheless
    hedge_per_100 = hedge_total / max(1, word_count / 100)
    check2 = max(0.0, 1.0 - hedge_per_100)

    # ---- Check 3: Adjective inflation ----
    _ADJECTIVES = [
        "robust",
        "comprehensive",
        "crucial",
        "paramount",
        "multifaceted",
        "holistic",
        "dynamic",
        "vibrant",
    ]
    adj_hits = sum(1 for adj in _ADJECTIVES if adj in content_lower)
    adj_per_100 = adj_hits / max(1, word_count / 100)
    check3 = max(0.0, 1.0 - adj_per_100)

    # ---- Check 4: Bullet-point addiction (form-factor-aware) ----
    form_factor = _resolve_form_factor(content_type)
    bullet_lines = sum(
        1
        for line in lines
        if line.strip().startswith(("-", "*")) or _re.match(r"^\d+[.)]\s", line.strip())
    )
    non_bullet_lines = sum(
        1
        for line in lines
        if line.strip()
        and not line.strip().startswith(("-", "*"))
        and not _re.match(r"^\d+[.)]\s", line.strip())
    )
    total_meaningful = bullet_lines + non_bullet_lines
    if total_meaningful > 0:
        bullet_ratio = bullet_lines / total_meaningful
    else:
        bullet_ratio = 0.0

    # ── Form-factor-aware thresholds ──
    if form_factor == "bullet":
        # Bullet content is expected to have high bullet ratio — relaxed
        if bullet_ratio > 0.95:
            check4 = 0.3  # still penalize if it's ALL bullets
        elif bullet_ratio > 0.8:
            check4 = 0.7
        else:
            check4 = 1.0
    elif form_factor in ("short_paragraph", "paragraph"):
        # Short text: moderate tolerance
        if bullet_ratio > 0.7:
            check4 = 0.0
        elif bullet_ratio > 0.4:
            check4 = 0.5
        else:
            check4 = 1.0
    else:
        # Default (section, passage): strict — bullets should be sparse
        if bullet_ratio > 0.7:
            check4 = 0.0
        elif bullet_ratio > 0.4:
            check4 = 0.5
        else:
            check4 = 1.0

    # ---- Check 5: No personal stance (regex-based) ----
    _PERSONAL_REGEX = _re.compile(
        r"\b(I|we|my|our|me|us)\s+(am|was|have|had|did|"
        r"spent|found|fixed|debugged|tried|wrote|built|"
        r"think|believe|noticed|discovered|feel|\w+ed|\w+ing)\b",
        _re.IGNORECASE,
    )
    personal_hits = len(_PERSONAL_REGEX.findall(content))
    check5 = min(1.0, personal_hits / 3.0)

    # ---- Check 6: Formulaic transitions ----
    _TRANSITIONS = [
        "first",
        "secondly",
        "third",
        "finally",
        "in conclusion",
        "lastly",
        "to begin",
        "next",
        "additionally",
    ]
    transition_hits = 0
    for para in paragraphs:
        para_lower = para.lower()
        if any(para_lower.startswith(t) for t in _TRANSITIONS):
            transition_hits += 1
    check6 = max(0.0, 1.0 - (transition_hits / para_count))

    # ---- Check 7: Burstiness (word clustering) ----
    # Human writers reuse topical words in bursts; AI distributes evenly.
    # Measure variance of inter-arrival gaps for top 5 content words.
    content_words = [w.lower() for w in words if w.isalpha() and len(w) > 2]
    if len(content_words) >= 10:
        word_counts = _Counter(content_words)
        top5 = [w for w, _ in word_counts.most_common(5)]
        burst_variances: list[float] = []
        for w in top5:
            positions = [i for i, cw in enumerate(content_words) if cw == w]
            if len(positions) >= 3:
                gaps = [
                    positions[i + 1] - positions[i] for i in range(len(positions) - 1)
                ]
                if len(gaps) >= 2:
                    try:
                        gap_mean = _mean(gaps)
                        gap_var = _mean((g - gap_mean) ** 2 for g in gaps)
                        burst_variances.append(gap_var)
                    except Exception:  # noqa: BLE001
                        _log = _logging.getLogger("saimon.evaluate.ai_detection")
                        _log.debug(
                            "Burstiness variance computation failed", exc_info=True
                        )
        if burst_variances:
            avg_burst_var = _mean(burst_variances)
            # High variance (>3) = bursty/human, low variance (<1) = uniform/AI
            # Normalize: 0 when var < 0.5, 1 when var > 3
            check7 = min(1.0, max(0.0, (avg_burst_var - 0.5) / 2.5))
        else:
            check7 = 0.5  # neutral — not enough data
    else:
        check7 = 0.5  # neutral — too few content words

    # ---- Check 8: Perplexity proxy (TTR + hapax legomena) ----
    words_lower = [w.lower() for w in words if w.isalpha()]
    if len(words_lower) >= 10:
        unique_count = len(set(words_lower))
        ttr = unique_count / len(words_lower)  # type-token ratio
        word_freq = _Counter(words_lower)
        hapax_count = sum(1 for c in word_freq.values() if c == 1)
        hapax_ratio = hapax_count / len(words_lower)

        # TTR: 0.35 (AI-like) → 0.0, 0.7+ (human) → 1.0
        ttr_score = min(1.0, max(0.0, (ttr - 0.35) / 0.35))
        # Hapax: 0.25 (AI-like) → 0.0, 0.55+ (human) → 1.0
        hapax_score = min(1.0, max(0.0, (hapax_ratio - 0.25) / 0.30))
        check8 = (ttr_score + hapax_score) / 2.0
    else:
        check8 = 0.5  # neutral

    # ---- Check 9: Sentence length variance ----
    sent_lengths = [len(s.split()) for s in sentences if s.split()]
    if len(sent_lengths) >= 4:
        try:
            sent_mean = _mean(sent_lengths)
            sent_std = _stdev(sent_lengths)
            cv = (
                sent_std / sent_mean if sent_mean > 0 else 0.0
            )  # coefficient of variation
            # CV < 0.3 = suspiciously uniform (AI-like) → 0.0
            # CV > 0.9 = natural variation (human) → 1.0
            cv_score = min(1.0, max(0.0, (cv - 0.3) / 0.6))

            # Penalty for sentences >50 words (older model trait)
            long_sents = sum(1 for sl in sent_lengths if sl > 50)
            long_penalty = min(1.0, long_sents / max(1, len(sent_lengths)))
            check9 = cv_score * (1.0 - long_penalty * 0.5)
            check9 = max(0.0, check9)
        except Exception:  # noqa: BLE001
            check9 = 0.5
    else:
        check9 = 0.5  # neutral

    # ---- Check 10: Punctuation diversity ----
    punctuation_chars = {
        c
        for c in content
        if c in (".", ",", ";", ":", "!", "?", "—", "–", "…", "(", ")", '"', "'", "-")
    }
    punct_per_100 = len(punctuation_chars) / max(1, word_count / 100)
    # >8 unique types per 100 words = human-like → 1.0
    # <3 unique types per 100 = AI-like → 0.0
    check10 = min(1.0, max(0.0, (punct_per_100 - 3.0) / 5.0))

    # ---- Check 11: Corporate neutrality ----
    # Detect impersonal/balanced/hedged tone — hallmark of AI-generated
    # corporate or explanatory text. High hedging + low personal stance = AI signal.
    _CORPORATE_NEUTRALITY = [
        "can reduce",
        "may help",
        "offers several",
        "contribute to",
        "without fundamentally",
        "these capabilities",
        "practical benefits",
        "can lead to",
        "may result in",
        "has the potential",
        "it is possible",
        "in many cases",
        "tends to",
        "generally speaking",
        "for the most part",
        "in general",
        "it can be argued",
        "one might argue",
        "some may argue",
        "it is often said",
        "it is commonly believed",
        "a wide range of",
        "a variety of",
        "various factors",
        "several key",
        "multiple aspects",
        "numerous ways",
        "can be seen as",
        "can be viewed as",
        "can be considered",
        "it is reasonable to",
        "it is fair to say",
        "strikes a balance",
        "finds a middle ground",
        "on balance",
        "all things considered",
    ]
    corp_hits = sum(1 for phrase in _CORPORATE_NEUTRALITY if phrase in content_lower)
    corp_per_100 = corp_hits / max(1, word_count / 100)
    # High corporate neutrality → AI-like (lower score)
    check11 = max(0.0, 1.0 - corp_per_100 * 2.0)

    # ---- Check 12: Sentence starter diversity ----
    # AI tends to reuse the same sentence starters; humans vary them naturally.
    # Extract first 1-2 words of each sentence and compute unique/total ratio.
    sent_starters: list[str] = []
    for s in sentences:
        stripped = s.strip()
        if stripped:
            # Get first 1-2 words as the "starter fingerprint"
            starter_words = stripped.split()[:2]
            starter = " ".join(starter_words).lower()
            sent_starters.append(starter)
    if len(sent_starters) >= 3:
        unique_starters = len(set(sent_starters))
        starter_diversity = unique_starters / len(sent_starters)
        # <0.5 diversity = AI-like → 0.0; >0.9 = human → 1.0
        check12 = min(1.0, max(0.0, (starter_diversity - 0.5) / 0.4))
    else:
        check12 = 0.5  # neutral — too few sentences

    # ---- Aggregate (weighted) ----
    # template phrases 2x, adjective inflation 2x, rest 1x
    checks = [
        check1,
        check2,
        check3,
        check4,
        check5,
        check6,
        check7,
        check8,
        check9,
        check10,
        check11,
        check12,
    ]
    weights = [2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    total_weight = sum(weights)
    overall = sum(c * w for c, w in zip(checks, weights)) / total_weight

    # Build justification
    check_labels = []
    if check1 < 0.7:
        check_labels.append(f"{template_hits} template phrases ({check1:.2f})")
    if check2 < 0.7:
        check_labels.append(f"over-hedging ({check2:.2f})")
    if check3 < 0.7:
        check_labels.append(f"{adj_hits} inflated adjectives ({check3:.2f})")
    if check4 < 0.7:
        check_labels.append(f"bullet ratio {bullet_ratio:.0%} ({check4:.2f})")
    if check5 < 0.7:
        check_labels.append(f"no personal stance ({check5:.2f})")
    if check6 < 0.7:
        check_labels.append(f"{transition_hits} formulaic transitions ({check6:.2f})")
    if check7 < 0.7:
        check_labels.append(f"low burstiness ({check7:.2f})")
    if check8 < 0.7:
        check_labels.append(f"low lexical diversity ({check8:.2f})")
    if check9 < 0.7:
        check_labels.append(f"uniform sentences ({check9:.2f})")
    if check10 < 0.7:
        check_labels.append(f"narrow punctuation ({check10:.2f})")
    if check11 < 0.7:
        check_labels.append(f"corporate neutrality ({check11:.2f})")
    if check12 < 0.7:
        check_labels.append(f"low starter diversity ({check12:.2f})")

    if not check_labels:
        justification = (
            f"AI detection: {overall:.2f}. Deterministic heuristic — not an ML classifier. "
            f"No strong AI fingerprints detected in {word_count} words across "
            f"{sentence_count} sentences."
        )
    else:
        justification = (
            f"AI detection: {overall:.2f}. Deterministic heuristic — not an ML classifier. "
            f"Flags: {'; '.join(check_labels)}. "
            f"({word_count} words, {sentence_count} sentences)"
        )

    return {
        "criterion": "ai_detection",
        "score": round(overall, 2),
        "max_score": 1.0,
        "justification": justification,
    }


def _score_criterion(
    criterion: str,
    content: str,
    tone: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Return a score for a single criterion (heuristic fallback)."""
    word_count = len(content.split())
    char_count = len(content)

    scorers: dict[str, Any] = {
        "clarity": lambda: {
            "score": 0.75,
            "justification": (
                f"Content is {word_count} words. Heuristic clarity score."
            ),
        },
        "completeness": lambda: {
            "score": 0.70,
            "justification": (
                f"Content length: {char_count} chars. Heuristic completeness score."
            ),
        },
        "coherence": lambda: {
            "score": 0.80,
            "justification": "Heuristic coherence score.",
        },
        "conciseness": lambda: {
            "score": 0.85 if word_count < 500 else 0.65,
            "justification": f"Content is {word_count} words. Heuristic conciseness score.",
        },
        "tone_match": lambda: {
            "score": 0.72,
            "justification": f"Requested tone: {tone or 'neutral'}. Heuristic tone_match score.",
        },
        "ai_detection": lambda: _score_ai_detection(
            content, tone, content_type=content_type
        ),
    }

    scorer = scorers.get(criterion)
    if scorer is None:
        return {"score": 0.5, "justification": f"Unknown criterion: {criterion}"}

    result = scorer()
    return {
        "criterion": criterion,
        "score": round(result["score"], 2),
        "max_score": 1.0,
        "justification": result["justification"],
    }


def _compute_overall(
    scores: list[dict[str, Any]] | None,
) -> float:
    """Compute a weighted overall score from individual criterion scores."""
    if not scores:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for s in scores:
        criterion_name = s["criterion"]
        weight = _CRITERIA.get(criterion_name, {}).get("weight", 1.0 / len(_CRITERIA))
        weighted_sum += s["score"] * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


# ---------------------------------------------------------------------------
# tool: evaluate_content
# ---------------------------------------------------------------------------


@app.post("/tools/evaluate_content")
async def evaluate_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    content = payload.parameters.get("content")
    if not content:
        return _error(payload.trace_id, "Parameter 'content' is required.")

    requested = payload.parameters.get("criteria")
    if requested is not None:
        # Accept comma-separated string, JSON-encoded list, or Python list
        if isinstance(requested, str):
            # Try JSON decode first (handles '["clarity","conciseness"]')
            import json as _json

            try:
                parsed = _json.loads(requested)
                if isinstance(parsed, list):
                    requested = parsed
                else:
                    requested = [c.strip() for c in requested.split(",") if c.strip()]
            except (_json.JSONDecodeError, ValueError):
                requested = [c.strip() for c in requested.split(",") if c.strip()]
        if not isinstance(requested, list):
            return _error(
                payload.trace_id, "Parameter 'criteria' must be a list of strings."
            )
        # Strip quotes/brackets from individual entries
        cleaned: list[str] = []
        for c in requested:
            if not isinstance(c, str):
                return _error(
                    payload.trace_id, "Parameter 'criteria' must be a list of strings."
                )
            cleaned.append(c.strip().strip('"').strip("'").strip("[").strip("]"))
        requested = cleaned
        # Validate all requested criteria exist
        unknown = [c for c in requested if c not in _CRITERIA]
        if unknown:
            supported = ", ".join(sorted(_CRITERIA.keys()))
            return _error(
                payload.trace_id,
                f"Unknown criteria: {', '.join(repr(u) for u in unknown)}. "
                f"Supported: {supported}.",
            )
        criteria_names = requested
    else:
        criteria_names = list(_CRITERIA.keys())

    tone = payload.parameters.get("tone")

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="evaluate_content",
        content_length=len(content),
        criteria_count=len(criteria_names),
    )

    # Score each criterion — try LLM first, fall back to heuristic.
    # EXCEPT ai_detection: always uses the deterministic multi-check heuristic.
    # LLMs cannot reliably detect their own output — using the LLM for
    # ai_detection produces dangerously misleading scores (e.g. 0.9 for
    # obviously AI-generated text). This criterion NEVER calls the LLM.
    llm_criteria = [c for c in criteria_names if c != "ai_detection"]
    has_ai_detection = "ai_detection" in criteria_names

    scores: list[dict[str, Any]] = []
    if _llm_client is not None and llm_criteria:
        try:
            scores = await _llm_evaluate(llm_criteria, content, tone)
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            scores = [
                _score_criterion(c, content, tone, content_type=payload.content_type)
                for c in llm_criteria
            ]
    elif llm_criteria:
        scores = [
            _score_criterion(c, content, tone, content_type=payload.content_type)
            for c in llm_criteria
        ]

    # Always append ai_detection via deterministic heuristic if requested
    if has_ai_detection:
        scores.append(
            _score_ai_detection(content, tone, content_type=payload.content_type)
        )

    # Compute overall score
    overall = _compute_overall(scores)

    citations = [s.identifier for s in payload.sources] if payload.sources else []

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "scores": scores,
            "overall_score": overall,
            "criteria_count": len(scores),
        },
        citations=citations,
    )
    logger.log_response(status=resp.status, citations_count=len(resp.citations or []))
    return resp


# ---------------------------------------------------------------------------
# tool: list_criteria
# ---------------------------------------------------------------------------


@app.post("/tools/list_criteria")
async def list_criteria(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(content_type=payload.content_type, tool="list_criteria")

    criteria = [
        {
            "name": name,
            "description": schema["description"],
            "weight": schema["weight"],
        }
        for name, schema in _CRITERIA.items()
    ]

    resp = _ok(trace_id=payload.trace_id, data={"criteria": criteria})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_criterion_detail
# ---------------------------------------------------------------------------


@app.post("/tools/get_criterion_detail")
async def get_criterion_detail(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    criterion_name = payload.parameters.get("criterion_name")
    if not criterion_name:
        return _error(payload.trace_id, "Parameter 'criterion_name' is required.")

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_criterion_detail",
        criterion_name=criterion_name,
    )

    schema = _CRITERIA.get(criterion_name)
    if schema is None:
        supported = ", ".join(sorted(_CRITERIA.keys()))
        return _error(
            payload.trace_id,
            f"Unknown criterion: {criterion_name!r}. Supported: {supported}.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: evaluate_voice (writing style/voice consistency)
# ---------------------------------------------------------------------------


@app.post("/tools/evaluate_voice")
async def evaluate_voice_tool(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    scene_text = payload.parameters.get("scene_text")
    voice_profiles = payload.parameters.get("voice_profiles")
    if not scene_text or not str(scene_text).strip():
        return _error(payload.trace_id, "Parameter 'scene_text' is required.")
    if not isinstance(voice_profiles, list):
        return _error(payload.trace_id, "Parameter 'voice_profiles' must be a list.")

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="evaluate_voice",
        profile_count=len(voice_profiles),
    )

    result = evaluate_voice(str(scene_text), voice_profiles)
    resp = _ok(payload.trace_id, data=result)
    logger.log_response(status=resp.status)
    return resp
