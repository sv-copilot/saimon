"""ninth_circuit.py — Ninth Circuit citation graph experiment (architecture §7).

Runs the seven-step citation pipeline against recorded fixtures (no live keys):

1. Load ~200 Ninth Circuit opinions (2020-2024)  [recorded fixture]
2. Extract citations from opinion text           [legal.parse_citation]
3. Build the directed citation graph             [in-memory adjacency]
4. Overlay citator data                          [legal.reconcile_citators]
5. Extract brief citations                       [recorded fixture]
6. Compute the opinion-vs-brief delta            [legal.build_usage_layer]
7. Report findings                               [deterministic memo]

Run from the repo root::

    python plugins/legal/experiments/ninth_circuit.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Make ``python plugins/legal/experiments/ninth_circuit.py`` runnable from the
# repo root without a package install on the path.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.legal.tools.parse_citation import parse_citation
from plugins.legal.tools.reconcile_citators import reconcile_citators
from plugins.legal.tools.usage_layer import build_usage_layer

# ---------------------------------------------------------------------------
# recorded fixtures (representative subset — live mode pulls ~200 opinions)
# ---------------------------------------------------------------------------

AUTHORITY_FIXTURES: list[dict[str, Any]] = [
    {
        "citation": "410 U.S. 113",
        "citators": {"courtlistener": "followed", "shepards": "followed"},
        "usage": {"3m": 12, "6m": 25, "12m": 48, "24m": 90},
    },
    {
        "citation": "304 U.S. 64",
        "citators": {"courtlistener": "followed", "shepards": "followed"},
        "usage": {"3m": 8, "6m": 18, "12m": 35, "24m": 70},
    },
    {
        "citation": "141 S. Ct. 740",
        "citators": {"courtlistener": "followed", "shepards": "positive"},
        "usage": {"3m": 4, "6m": 9, "12m": 15, "24m": 28},
    },
    {
        "citation": "19 F.4th 1100",
        "citators": {"courtlistener": "cited", "shepards": "positive"},
        "usage": {"3m": 0, "6m": 1, "12m": 2, "24m": 4},
    },
    {
        "citation": "9 F.4th 100",
        "citators": {"courtlistener": "overruled", "shepards": "red"},
        "usage": {"3m": 0, "6m": 0, "12m": 0, "24m": 0},
    },
]

OPINION_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "ninth-2020-1",
        "decided_date": "2020-03-15",
        "cites": ["410 U.S. 113", "304 U.S. 64"],
    },
    {
        "id": "ninth-2021-1",
        "decided_date": "2021-06-10",
        "cites": ["141 S. Ct. 740", "410 U.S. 113"],
    },
    {
        "id": "ninth-2022-1",
        "decided_date": "2022-09-01",
        "cites": ["304 U.S. 64"],
    },
    {
        "id": "ninth-2023-1",
        "decided_date": "2023-01-20",
        "cites": ["19 F.4th 1100"],
    },
    {
        "id": "ninth-2024-1",
        "decided_date": "2024-05-05",
        "cites": [],
    },
]

BRIEF_FIXTURES: list[dict[str, Any]] = [
    {"id": "brief-a", "cites": ["410 U.S. 113"]},
    {"id": "brief-b", "cites": ["410 U.S. 113", "141 S. Ct. 740"]},
    {"id": "brief-c", "cites": ["304 U.S. 64"]},
    {"id": "brief-d", "cites": ["9 F.4th 100"]},
]


# ---------------------------------------------------------------------------
# pipeline steps
# ---------------------------------------------------------------------------


def _load_opinions(opinions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Step 1: load Ninth Circuit opinions (recorded fixtures here)."""
    return opinions if opinions is not None else OPINION_FIXTURES


def _extract_citations(
    opinions: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Step 2: normalize every cited authority with ``legal.parse_citation``.

    Returns a raw->canonical map plus accuracy stats.
    """
    canonical_by_raw: dict[str, str] = {}
    recognized = 0
    total = 0
    for opinion in opinions:
        for raw in opinion.get("cites", []) or []:
            total += 1
            parsed = parse_citation(str(raw))
            canonical = parsed["canonical"]
            canonical_by_raw[str(raw)] = canonical
            if parsed["format"] != "unknown":
                recognized += 1
    accuracy = (recognized / total) if total else 1.0
    return canonical_by_raw, {
        "total": total,
        "recognized": recognized,
        "accuracy": round(accuracy, 4),
    }


def _build_graph(
    opinions: list[dict[str, Any]], canonical_by_raw: dict[str, str]
) -> dict[str, Any]:
    """Step 3: build the directed opinion->authority citation graph."""
    edges: list[tuple[str, str]] = []
    indegree: dict[str, int] = {}
    for opinion in opinions:
        for raw in opinion.get("cites", []) or []:
            target = canonical_by_raw[str(raw)]
            edges.append((opinion["id"], target))
            indegree[target] = indegree.get(target, 0) + 1
    nodes = sorted({node for edge in edges for node in edge})
    return {"nodes": nodes, "edges": edges, "indegree": indegree}


def _overlay_citators(
    authorities: list[dict[str, Any]],
) -> dict[str, str]:
    """Step 4: reconcile citator data for each authority."""
    classifications: dict[str, str] = {}
    for authority in authorities:
        result = reconcile_citators(
            authority["citation"],
            authority["citators"],
            authority["usage"],
        )
        classifications[authority["citation"]] = result["classification"]
    return classifications


def _brief_tally(briefs: list[dict[str, Any]]) -> dict[str, int]:
    """Step 5: tally brief citations per authority."""
    counts: dict[str, int] = {}
    for brief in briefs:
        for raw in brief.get("cites", []) or []:
            counts[str(raw)] = counts.get(str(raw), 0) + 1
    return counts


def run_experiment(
    opinions: list[dict[str, Any]] | None = None,
    authorities: list[dict[str, Any]] | None = None,
    briefs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the seven-step pipeline and return the research report."""
    opinion_data = _load_opinions(opinions)
    authority_data = authorities if authorities is not None else AUTHORITY_FIXTURES
    brief_data = briefs if briefs is not None else BRIEF_FIXTURES

    canonical_by_raw, parse_stats = _extract_citations(opinion_data)
    graph = _build_graph(opinion_data, canonical_by_raw)
    classifications = _overlay_citators(authority_data)
    brief_counts = _brief_tally(brief_data)

    # Step 6: opinion-cited (indegree) vs brief-cited (tally).
    citations = sorted(set(graph["indegree"]) | set(brief_counts))
    authorities_for_layer = [
        {
            "citation": citation,
            "opinion_citations": graph["indegree"].get(citation, 0),
            "brief_citations": brief_counts.get(citation, 0),
        }
        for citation in citations
    ]
    usage = build_usage_layer(authorities_for_layer)

    brief_cited_total = len(
        [row for row in usage["rows"] if row["brief_citations"] > 0]
    )
    brief_only_percent = (
        round(usage["stats"]["brief_only_count"] / brief_cited_total * 100, 1)
        if brief_cited_total
        else 0.0
    )

    # Step 7: deterministic research memo.
    lines = [
        "Ninth Circuit citation graph — research memo",
        "==========================================",
        usage["headline"],
        (
            f"{brief_only_percent}% of brief-cited authorities are not in the "
            "opinion graph."
        ),
        (
            f"Citation parse accuracy: {parse_stats['accuracy']} "
            f"({parse_stats['recognized']}/{parse_stats['total']})."
        ),
        "Authority classifications:",
    ]
    for authority in authority_data:
        state = classifications.get(authority["citation"], "UNKNOWN")
        lines.append(f"  - {authority['citation']}: {state}")
    memo = "\n".join(lines)

    return {
        "steps_completed": 7,
        "headline": usage["headline"],
        "avoided_count": usage["avoided_count"],
        "brief_only_percent": brief_only_percent,
        "parse_stats": parse_stats,
        "graph": {
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        },
        "classifications": classifications,
        "usage": usage,
        "memo": memo,
    }


def main() -> None:
    """Print the research memo to stdout."""
    report = run_experiment()
    print(report["memo"])


if __name__ == "__main__":
    main()
