"""writing_style.py — style/voice consistency evaluation (slice #77).

Domain-agnostic primitive for the writing domain: score a scene against
per-character/POV voice profiles and flag drift.  Pure and synchronous — no
network I/O and no LLM dependency.

A voice profile is a dict::

    {"name": "Mara Voss", "markers": ["quiet", "measured"], "avoid": ["shouted"]}

``markers`` are words that signal the voice; ``avoid`` are words that contradict
it.  The score rewards marker coverage and penalizes avoid-word occurrences;
drift findings cite the offending line and the expected profile.
"""

from __future__ import annotations

from typing import Any


def _split_lines(scene_text: str) -> list[str]:
    return [line for line in (scene_text or "").splitlines() if line.strip()]


def _score_profile(profile: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    name = str(profile.get("name", "unnamed"))
    markers = [str(m).lower() for m in profile.get("markers", [])]
    avoid = [str(a).lower() for a in profile.get("avoid", [])]

    text = " ".join(lines).lower()
    marker_hits = sum(1 for marker in markers if marker in text)
    marker_count = len(markers)

    if marker_count:
        base = 100.0 * (marker_hits / marker_count)
    else:
        base = 50.0  # no markers to match — neutral base

    avoid_hits = 0
    for avoid_word in avoid:
        for line in lines:
            if avoid_word in line.lower():
                avoid_hits += 1

    score = max(0, min(100, round(base - 40.0 * min(avoid_hits, 2))))
    return {
        "name": name,
        "score": score,
        "marker_hits": marker_hits,
        "marker_count": marker_count,
        "avoid_hits": avoid_hits,
    }


def evaluate_voice(
    scene_text: str, voice_profiles: list[dict[str, Any]]
) -> dict[str, Any]:
    """Score *scene_text* against *voice_profiles* and report drift.

    Returns a 0-100 style-consistency score (the mean of per-profile scores),
    a list of drift findings (``{"finding", "line", "profile", "expected"}``),
    and the per-profile score breakdown.
    """
    lines = _split_lines(scene_text)
    profiles = voice_profiles or []

    findings: list[dict[str, Any]] = []
    profile_scores: list[dict[str, Any]] = []
    for profile in profiles:
        name = str(profile.get("name", "unnamed"))
        avoid = [str(a).lower() for a in profile.get("avoid", [])]
        profile_scores.append(_score_profile(profile, lines))
        for avoid_word in avoid:
            for line in lines:
                if avoid_word in line.lower():
                    findings.append(
                        {
                            "finding": "voice_drift",
                            "line": line.strip(),
                            "profile": name,
                            "expected": avoid_word,
                        }
                    )

    if profile_scores:
        score = round(sum(p["score"] for p in profile_scores) / len(profile_scores))
    else:
        score = 0

    return {
        "score": score,
        "findings": findings,
        "profiles": profile_scores,
    }
