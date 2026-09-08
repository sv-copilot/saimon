"""content_ops_seed.py — canonical content-ops knowledge-graph seed data.

SAIMON-CONTENT-OPS-KG-SEED-1 (#210): the content-ops pipeline's knowledge graph
was empty of its own node types, so ``search_knowledge_graph`` and
``explore_content`` returned 0 for topical queries.  This module is the single
source of truth for the content-ops node/edge schema and the canonical anchors
that bootstrap it:

- node types: ``profile_fact``, ``source``, ``topic``, ``lifecycle_stage``,
  ``post``
- edge types: ``cites``, ``covers``, ``stage_of``, ``grounds``, ``related_to``

Stable ``node_id`` values are derived deterministically (UUIDv5) from each
node's canonical key, so the seed is re-runnable and idempotent: re-running
against an existing database never creates duplicate nodes or edges.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Stable-id namespace
# ---------------------------------------------------------------------------

CONTENT_OPS_NAMESPACE = uuid.UUID("6b2e4a1e-8c0f-4f0e-9a3d-7f6c1a9b2d5e")


def stable_node_id(key: str) -> str:
    """Return the deterministic UUIDv5 for a canonical node key."""
    return str(uuid.uuid5(CONTENT_OPS_NAMESPACE, key))


# ---------------------------------------------------------------------------
# Node + edge schema
# ---------------------------------------------------------------------------

CONTENT_OPS_CONTENT_TYPES: list[dict[str, Any]] = [
    {
        "name": "profile_fact",
        "description": (
            "A verifiable public fact about the operator profile "
            "(resume/profile anchors used to ground brand claims)."
        ),
        "required_params": [],
        "optional_params": [],
        "voice_profile": None,
    },
    {
        "name": "source",
        "description": (
            "A cited theory or reference (DOI or exact title) used as a "
            "verification anchor for theory claims."
        ),
        "required_params": [],
        "optional_params": [],
        "voice_profile": None,
    },
    {
        "name": "topic",
        "description": "A topical entity in the content-ops knowledge graph.",
        "required_params": [],
        "optional_params": [],
        "voice_profile": None,
    },
    {
        "name": "lifecycle_stage",
        "description": "A stage in the 11-step content-ops lifecycle spine.",
        "required_params": [],
        "optional_params": [],
        "voice_profile": None,
    },
    {
        "name": "post",
        "description": "A content post produced by the content-ops pipeline.",
        "required_params": [],
        "optional_params": [],
        "voice_profile": None,
    },
]

CONTENT_OPS_EDGE_TYPES: list[str] = [
    "cites",
    "covers",
    "stage_of",
    "grounds",
    "related_to",
]


def _node(
    key: str,
    content_type: str,
    title: str,
    body: str,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "key": key,
        "content_type": content_type,
        "title": title,
        "body": body,
        "metadata": metadata,
    }


def _edge(
    source_key: str,
    target_key: str,
    relation_type: str,
    weight: float = 1.0,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "target_key": target_key,
        "relation_type": relation_type,
        "weight": weight,
        "metadata": metadata,
    }

# ---------------------------------------------------------------------------
# Canonical anchors
# ---------------------------------------------------------------------------

PROFILE_FACTS: list[dict[str, Any]] = [
    _node(
        "profile_fact/spencer-varadi-name",
        "profile_fact",
        "Spencer Varadi",
        "Spencer Varadi is the operator of the Saimon platform.",
        fact_type="name",
        public=True,
    ),
    _node(
        "profile_fact/spencer-varadi-location",
        "profile_fact",
        "San Francisco, CA",
        "Spencer Varadi is based in San Francisco, CA.",
        fact_type="location",
        public=True,
    ),
    _node(
        "profile_fact/spencer-varadi-linkedin",
        "profile_fact",
        "linkedin.com/in/spencervaradi",
        "Spencer Varadi's public LinkedIn profile is "
        "https://linkedin.com/in/spencervaradi.",
        fact_type="linkedin",
        url="https://linkedin.com/in/spencervaradi",
        public=True,
    ),
    _node(
        "profile_fact/spencer-varadi-title",
        "profile_fact",
        "Vice President of Digital Product",
        "Spencer Varadi's functional title is Vice President of Digital Product.",
        fact_type="title",
        public=True,
    ),
]

SOURCES: list[dict[str, Any]] = [
    _node(
        "source/deci-ryan-1985",
        "source",
        "Intrinsic Motivation and Self-Determination in Human Behavior",
        "Deci, E. L., & Ryan, R. M. (1985). Intrinsic Motivation and "
        "Self-Determination in Human Behavior. Springer.",
        doi="10.1007/978-1-4899-2271-7",
        authors=["Edward L. Deci", "Richard M. Ryan"],
        year=1985,
        theory="self_determination_theory",
    ),
    _node(
        "source/bakker-demerouti-2007",
        "source",
        "The Job Demands-Resources model: state of the art",
        "Bakker, A. B., & Demerouti, E. (2007). The Job Demands-Resources "
        "model: state of the art. Journal of Managerial Psychology, "
        "22(3), 309-328.",
        doi="10.1108/02683940710733115",
        authors=["Arnold B. Bakker", "Evangelia Demerouti"],
        year=2007,
        theory="job_demands_resources",
    ),
    _node(
        "source/luthans-youssef-avolio-2007",
        "source",
        "Psychological Capital: Developing the Human Competitive Edge",
        "Luthans, F., Youssef, C. M., & Avolio, B. J. (2007). Psychological "
        "Capital: Developing the Human Competitive Edge. Oxford University "
        "Press.",
        isbn="978-0-19-518752-6",
        authors=["Fred Luthans", "Carolyn M. Youssef", "Bruce J. Avolio"],
        year=2007,
        theory="psychological_capital",
    ),
    _node(
        "source/organ-1988",
        "source",
        "Organizational Citizenship Behavior: The Good Soldier Syndrome",
        "Organ, D. W. (1988). Organizational Citizenship Behavior: The Good "
        "Soldier Syndrome. Lexington Books.",
        isbn="978-0-669-11788-7",
        authors=["Dennis W. Organ"],
        year=1988,
        theory="organizational_citizenship_behavior",
    ),
    _node(
        "source/locke-latham-1990",
        "source",
        "A Theory of Goal Setting & Task Performance",
        "Locke, E. A., & Latham, G. P. (1990). A Theory of Goal Setting & "
        "Task Performance. Prentice-Hall.",
        isbn="978-0-13-913138-2",
        authors=["Edwin A. Locke", "Gary P. Latham"],
        year=1990,
        theory="goal_setting_theory",
    ),
]


_LIFECYCLE_STAGE_NAMES: list[tuple[int, str]] = [
    (1, "intake"),
    (2, "research"),
    (3, "outline"),
    (4, "draft"),
    (5, "self_review"),
    (6, "verify"),
    (7, "graph"),
    (8, "gate"),
    (9, "edit"),
    (10, "publish"),
    (11, "measure"),
]

LIFECYCLE_STAGES: list[dict[str, Any]] = [
    _node(
        f"lifecycle_stage/{number}-{slug}",
        "lifecycle_stage",
        f"{number}. {slug.replace('_', ' ').title()}",
        f"Content-ops lifecycle stage {number}: {slug.replace('_', ' ').title()}.",
        stage_number=number,
        slug=slug,
        spine="content-ops",
    )
    for number, slug in _LIFECYCLE_STAGE_NAMES
]

TOPICS: list[dict[str, Any]] = [
    _node(
        "topic/self-determination-theory",
        "topic",
        "Self-Determination Theory",
        "Self-Determination Theory (Deci & Ryan) distinguishes intrinsic and "
        "extrinsic motivation and identifies autonomy, competence, and "
        "relatedness as basic psychological needs.",
        topic_type="theory",
    ),
    _node(
        "topic/job-demands-resources-model",
        "topic",
        "Job Demands-Resources Model",
        "The Job Demands-Resources model (Bakker & Demerouti) explains "
        "burnout and engagement as a function of job demands and job "
        "resources.",
        topic_type="theory",
    ),
    _node(
        "topic/ai-assisted-content-operations",
        "topic",
        "AI-Assisted Content Operations",
        "Content operations augmented by AI agents for research, drafting, "
        "verification, and publication.",
        topic_type="domain",
    ),
    _node(
        "topic/knowledge-graphs",
        "topic",
        "Knowledge Graphs",
        "Knowledge graphs represent entities and relationships as nodes and "
        "edges for grounded retrieval.",
        topic_type="domain",
    ),
    _node(
        "topic/brand-verification",
        "topic",
        "Brand Verification",
        "Verification of brand claims against seeded profile facts and cited "
        "sources.",
        topic_type="domain",
    ),
]

POSTS: list[dict[str, Any]] = [
    _node(
        "post/saimon-self-extending-platform",
        "post",
        "Saimon: a self-extending content platform",
        "Saimon is a self-extending platform of six atomic MCP services that "
        "share one knowledge graph.",
        stage="graph",
    ),
    _node(
        "post/sdt-content-operations",
        "post",
        "How Self-Determination Theory Shapes Content Operations",
        "Self-Determination Theory frames content operations around autonomy, "
        "competence, and relatedness.",
        stage="draft",
    ),
]

CONTENT_OPS_NODES: list[dict[str, Any]] = (
    PROFILE_FACTS + SOURCES + LIFECYCLE_STAGES + TOPICS + POSTS
)

CONTENT_OPS_EDGES: list[dict[str, Any]] = [
    _edge("topic/self-determination-theory", "source/deci-ryan-1985", "covers"),
    _edge(
        "topic/job-demands-resources-model",
        "source/bakker-demerouti-2007",
        "covers",
    ),
    _edge(
        "post/saimon-self-extending-platform",
        "profile_fact/spencer-varadi-name",
        "grounds",
    ),
    _edge(
        "post/saimon-self-extending-platform",
        "profile_fact/spencer-varadi-title",
        "grounds",
    ),
    _edge("post/sdt-content-operations", "source/deci-ryan-1985", "cites"),
    _edge(
        "post/sdt-content-operations",
        "source/bakker-demerouti-2007",
        "cites",
    ),
    _edge(
        "post/saimon-self-extending-platform",
        "lifecycle_stage/7-graph",
        "stage_of",
    ),
    _edge(
        "post/sdt-content-operations",
        "lifecycle_stage/4-draft",
        "stage_of",
    ),
    _edge(
        "topic/self-determination-theory",
        "topic/brand-verification",
        "related_to",
    ),
    _edge(
        "topic/knowledge-graphs",
        "topic/ai-assisted-content-operations",
        "related_to",
    ),
]



# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest() -> dict[str, Any]:
    """Build the stable seed manifest (nodes + edges with resolved ids)."""
    nodes = [{**node, "id": stable_node_id(node["key"])} for node in CONTENT_OPS_NODES]

    edges: list[dict[str, Any]] = []
    for edge in CONTENT_OPS_EDGES:
        edges.append(
            {
                "source_key": edge["source_key"],
                "target_key": edge["target_key"],
                "source_id": stable_node_id(edge["source_key"]),
                "target_id": stable_node_id(edge["target_key"]),
                "relation_type": edge["relation_type"],
                "weight": edge["weight"],
                "metadata": edge["metadata"],
            }
        )

    return {
        "content_types": [dict(ct) for ct in CONTENT_OPS_CONTENT_TYPES],
        "edge_types": list(CONTENT_OPS_EDGE_TYPES),
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Seeding (idempotent)
# ---------------------------------------------------------------------------


async def seed_content_ops_kg(db: Any) -> dict[str, Any]:
    """Register content-ops node types and upsert canonical anchors.

    Idempotent: content types are upserted, and nodes/edges are inserted with
    ``ON CONFLICT DO NOTHING`` on their stable ids / natural keys, so re-running
    never creates duplicates.
    """
    manifest = build_manifest()

    for ct in CONTENT_OPS_CONTENT_TYPES:
        await db.execute(
            "INSERT INTO content_type_registry "
            "(name, description, required_params, optional_params, voice_profile) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (name) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "required_params = EXCLUDED.required_params, "
            "optional_params = EXCLUDED.optional_params, "
            "voice_profile = EXCLUDED.voice_profile, "
            "updated_at = now()",
            ct["name"],
            ct["description"],
            json.dumps(ct["required_params"]),
            json.dumps(ct["optional_params"]),
            ct.get("voice_profile"),
        )

    for node in manifest["nodes"]:
        await db.execute(
            "INSERT INTO knowledge_graph_nodes "
            "(id, title, content_type, body, metadata, user_id) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, NULL) "
            "ON CONFLICT (id) DO NOTHING",
            node["id"],
            node["title"],
            node["content_type"],
            node["body"],
            json.dumps(node["metadata"]),
        )

    for edge in manifest["edges"]:
        await db.execute(
            "INSERT INTO knowledge_graph_edges "
            "(source_id, target_id, relation_type, weight, metadata) "
            "VALUES ($1, $2, $3, $4, $5::jsonb) "
            "ON CONFLICT (source_id, target_id, relation_type) DO NOTHING",
            edge["source_id"],
            edge["target_id"],
            edge["relation_type"],
            edge["weight"],
            json.dumps(edge["metadata"]),
        )

    return {
        "content_types": len(manifest["content_types"]),
        "node_count": len(manifest["nodes"]),
        "edge_count": len(manifest["edges"]),
    }


# ---------------------------------------------------------------------------
# Brand-claim grounding probe (acceptance #3)
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.'-]*")

_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "not", "but", "with", "from",
    "that", "this", "these", "those", "into", "its", "his", "her", "their",
    "has", "have", "had", "been", "being", "will", "would", "should", "could",
    "does", "did", "about", "over", "under", "also", "than", "then", "them",
}


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_PATTERN.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    }


def match_profile_facts(claim: str) -> list[dict[str, Any]]:
    """Return ``profile_fact`` nodes that lexically ground a brand claim."""
    claim_tokens = _tokens(claim)
    matches: list[dict[str, Any]] = []
    for node in PROFILE_FACTS:
        haystack = _tokens(f"{node['title']} {node['body']}")
        if claim_tokens & haystack:
            matches.append({**node, "id": stable_node_id(node["key"])})
    return matches


def verify_brand_claim(claim: str) -> dict[str, Any]:
    """Probe whether a sample brand claim is grounded by a seeded fact.

    Returns ``supported`` when at least one seeded ``profile_fact`` node anchors
    the claim, otherwise ``inconclusive``.  This is the seed-side grounding
    check that the content-ops verify path (SAIMON-VERIFY-THEORY-CITATIONS-1)
    consumes once ``profile_fact`` anchors are present.
    """
    grounds = match_profile_facts(claim)
    return {
        "verdict": "supported" if grounds else "inconclusive",
        "grounds": [g["key"] for g in grounds],
    }

