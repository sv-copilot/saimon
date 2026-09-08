"""Tests for SAIMON-CONTENT-OPS-KG-SEED-1 — content-ops KG seeding.

Covers the slice's TDD contract:
- the seed manifest loads with stable node ids,
- the node/edge schema fields validate,
- re-running the seed is idempotent (no duplicate nodes),
- a seeded graph can be probed through the real search/get_related query paths.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from research_shared import content_ops_seed as cos

# ---------------------------------------------------------------------------
# In-memory fake DB (emulates the knowledge-graph tables)
# ---------------------------------------------------------------------------


class InMemoryKG:
    """Minimal async fake for ``knowledge_graph_nodes``/``edges`` seeding."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.content_types: dict[str, bool] = {}

    async def execute(self, query: str, *args) -> str:
        q = query.strip().upper()
        if q.startswith("INSERT INTO CONTENT_TYPE_REGISTRY"):
            self.content_types[args[0]] = True
        elif "INSERT INTO KNOWLEDGE_GRAPH_NODES" in q:
            self.nodes.setdefault(
                args[0],
                {
                    "id": args[0],
                    "title": args[1],
                    "content_type": args[2],
                    "body": args[3],
                    "metadata": json.loads(args[4]),
                },
            )
        elif "INSERT INTO KNOWLEDGE_GRAPH_EDGES" in q:
            key = (args[0], args[1], args[2])
            self.edges.setdefault(
                key,
                {
                    "source_id": args[0],
                    "target_id": args[1],
                    "relation_type": args[2],
                    "weight": args[3],
                    "metadata": json.loads(args[4]),
                },
            )
        return "OK"

    async def fetch(self, query: str, *args):
        if "ILIKE" in query and "FROM knowledge_graph_nodes" in query:
            words = [
                str(a)[1:-1]
                for a in args
                if isinstance(a, str) and a.startswith("%") and a.endswith("%")
            ]
            limit = next((a for a in args if isinstance(a, int)), None)
            results = []
            for node in self.nodes.values():
                haystack = f"{node.get('title', '')} {node.get('body', '')}".lower()
                if all(w.lower() in haystack for w in words):
                    results.append(
                        {
                            "id": node["id"],
                            "title": node["title"],
                            "content_type": node["content_type"],
                            "relevance": float(
                                node.get("metadata", {}).get("relevance", 0.5)
                            ),
                        }
                    )
            return results[:limit] if limit else results

        if "FROM knowledge_graph_edges" in query and "JOIN knowledge_graph_nodes" in query:
            node_id = str(args[0])
            relation_type = next(
                (a for a in args[1:] if isinstance(a, str)), None
            )
            limit = next(
                (a for a in args if isinstance(a, int)), 20
            )
            outgoing = "e.source_id = $" in query and "e.target_id = $" not in query
            incoming = "e.target_id = $" in query and "e.source_id = $" not in query

            rows = []
            for edge in self.edges.values():
                if relation_type and edge["relation_type"] != relation_type:
                    continue
                if outgoing and edge["source_id"] != node_id:
                    continue
                if incoming and edge["target_id"] != node_id:
                    continue
                if (
                    not outgoing
                    and not incoming
                    and edge["source_id"] != node_id
                    and edge["target_id"] != node_id
                ):
                    continue
                other_id = (
                    edge["target_id"]
                    if edge["source_id"] == node_id
                    else edge["source_id"]
                )
                other = self.nodes.get(other_id)
                if other is None:
                    continue
                rows.append(
                    {
                        "edge_id": (
                            f"{edge['source_id']}:{edge['relation_type']}:"
                            f"{edge['target_id']}"
                        ),
                        "relation_type": edge["relation_type"],
                        "weight": edge["weight"],
                        "source_id": edge["source_id"],
                        "target_id": edge["target_id"],
                        "node_id": other_id,
                        "title": other["title"],
                        "content_type": other["content_type"],
                    }
                )
            return rows[:limit]

        if "SELECT count(*)" in query:
            return [{"cnt": len(self.nodes)}]

        return []

    async def fetchrow(self, query: str, *args):
        return None

    async def fetchval(self, query: str, *args):
        return None

    async def close(self) -> None:
        return None


async def _seed(db: InMemoryKG) -> dict:
    return await cos.seed_content_ops_kg(db)


def _manifest_node(manifest: dict, key: str) -> dict:
    for node in manifest["nodes"]:
        if node["key"] == key:
            return node
    raise AssertionError(f"missing manifest node: {key}")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_loads(self):
        manifest = cos.build_manifest()
        assert isinstance(manifest, dict)
        assert {"content_types", "edge_types", "nodes", "edges"} <= set(manifest)
        assert manifest["nodes"]
        assert manifest["edges"]

    def test_node_ids_are_stable_valid_uuids(self):
        first = cos.build_manifest()
        second = cos.build_manifest()
        assert [n["id"] for n in first["nodes"]] == [
            n["id"] for n in second["nodes"]
        ]
        seen: set[str] = set()
        for node in first["nodes"]:
            uuid.UUID(node["id"])  # raises if not a valid UUID
            assert node["id"] not in seen  # unique
            seen.add(node["id"])

    def test_manifest_lists_required_node_types(self):
        manifest = cos.build_manifest()
        types = {node["content_type"] for node in manifest["nodes"]}
        for expected in ("profile_fact", "source", "topic", "lifecycle_stage"):
            assert expected in types

    def test_committed_manifest_matches(self):
        manifest = cos.build_manifest()
        path = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "content_ops_seed_manifest.json"
        )
        with open(path, encoding="utf-8") as fh:
            committed = json.load(fh)
        assert [n["id"] for n in committed["nodes"]] == [
            n["id"] for n in manifest["nodes"]
        ]
        assert [e["relation_type"] for e in committed["edges"]] == [
            e["relation_type"] for e in manifest["edges"]
        ]


# ---------------------------------------------------------------------------
# Schema fields
# ---------------------------------------------------------------------------


class TestSchemaFields:
    def test_content_types_registered(self):
        names = {ct["name"] for ct in cos.CONTENT_OPS_CONTENT_TYPES}
        assert names == {
            "profile_fact",
            "source",
            "topic",
            "lifecycle_stage",
            "post",
        }

    def test_edge_types_registered(self):
        assert set(cos.CONTENT_OPS_EDGE_TYPES) == {
            "cites",
            "covers",
            "stage_of",
            "grounds",
            "related_to",
        }

    def test_nodes_have_required_fields(self):
        ct_names = {ct["name"] for ct in cos.CONTENT_OPS_CONTENT_TYPES}
        for node in cos.CONTENT_OPS_NODES:
            assert node["key"]
            assert node["title"]
            assert node["content_type"] in ct_names
            assert isinstance(node["body"], str)
            assert isinstance(node["metadata"], dict)

    def test_edges_reference_known_nodes_and_types(self):
        keys = {node["key"] for node in cos.CONTENT_OPS_NODES}
        edge_types = set(cos.CONTENT_OPS_EDGE_TYPES)
        for edge in cos.CONTENT_OPS_EDGES:
            assert edge["source_key"] in keys
            assert edge["target_key"] in keys
            assert edge["relation_type"] in edge_types

    def test_lifecycle_spine_has_eleven_stages(self):
        stages = [
            n for n in cos.CONTENT_OPS_NODES
            if n["content_type"] == "lifecycle_stage"
        ]
        assert len(stages) == 11
        numbers = sorted(n["metadata"]["stage_number"] for n in stages)
        assert numbers == list(range(1, 12))


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_rerun_does_not_duplicate_nodes_or_edges(self):
        db = InMemoryKG()
        first = await _seed(db)
        assert len(db.nodes) == first["node_count"]
        assert len(db.edges) == first["edge_count"]

        second = await _seed(db)
        assert second["node_count"] == first["node_count"]
        assert second["edge_count"] == first["edge_count"]
        assert len(db.nodes) == first["node_count"]
        assert len(db.edges) == first["edge_count"]



# ---------------------------------------------------------------------------
# Seed -> retrieval probe
# ---------------------------------------------------------------------------


class TestRetrievalProbe:
    async def test_search_knowledge_graph_returns_seeded_topics(self, monkeypatch):
        db = InMemoryKG()
        await _seed(db)

        sys.modules.pop("saimon_mcp.search.server", None)
        sys.modules.pop("saimon_mcp.search", None)
        from saimon_mcp.search import server as search_server

        monkeypatch.setattr(search_server, "_db_pool", db)

        results = await search_server._keyword_search("Self-Determination", 10, None)
        titles = [r["title"] for r in results]
        assert any("Self-Determination" in title for title in titles)

    def test_get_related_resolves_covers_and_grounds(self, monkeypatch):
        db = InMemoryKG()
        asyncio.run(_seed(db))
        manifest = cos.build_manifest()

        topic = _manifest_node(manifest, "topic/self-determination-theory")
        post = _manifest_node(manifest, "post/saimon-self-extending-platform")

        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-content-ops-key")
        sys.modules.pop("saimon_mcp.explore.server", None)
        from fastapi.testclient import TestClient

        import saimon_mcp.explore.server as explore_server

        explore_server._db_pool = db
        client = TestClient(explore_server.app)
        headers = {"X-Saimon-API-Key": "sk-test-content-ops-key"}

        covers = client.post(
            "/tools/get_related",
            json={
                "trace_id": str(uuid.uuid4()),
                "content_type": "explore",
                "parameters": {
                    "node_id": topic["id"],
                    "relation_type": "covers",
                    "direction": "outgoing",
                },
            },
            headers=headers,
        )
        assert covers.status_code == 200
        covers_data = covers.json()
        assert covers_data["status"] == "success"
        assert covers_data["data"]["total"] >= 1
        assert any(
            item["relation_type"] == "covers"
            for item in covers_data["data"]["related"]
        )

        grounds = client.post(
            "/tools/get_related",
            json={
                "trace_id": str(uuid.uuid4()),
                "content_type": "explore",
                "parameters": {
                    "node_id": post["id"],
                    "relation_type": "grounds",
                    "direction": "outgoing",
                },
            },
            headers=headers,
        )
        assert grounds.status_code == 200
        grounds_data = grounds.json()
        assert grounds_data["status"] == "success"
        assert grounds_data["data"]["total"] >= 1
        assert any(
            item["relation_type"] == "grounds"
            and item["node"]["content_type"] == "profile_fact"
            for item in grounds_data["data"]["related"]
        )


# ---------------------------------------------------------------------------
# Brand-claim grounding probe (acceptance #3)
# ---------------------------------------------------------------------------


class TestBrandClaimGrounding:
    def test_sample_brand_claim_verifies_supported(self):
        result = cos.verify_brand_claim(
            "Spencer Varadi is a Vice President of Digital Product"
        )
        assert result["verdict"] == "supported"
        assert result["grounds"]

    def test_unrelated_claim_is_inconclusive(self):
        result = cos.verify_brand_claim("The moon is made of green cheese")
        assert result["verdict"] == "inconclusive"
        assert result["grounds"] == []

