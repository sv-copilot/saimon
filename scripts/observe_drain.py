#!/usr/bin/env python3
"""observe_drain.py — project agent-observation content nodes into `observations`.

Agents (any Hermes bot) dump what they deem worth keeping with ONE call:

    saimon_store_content(content_type="observation", title="<label>",
                         body="<the claim>",
                         metadata='{"agent":"freebird","topic":"...",
                                    "source_url":"...","confidence":0.8}')

That lands cheaply in knowledge_graph_nodes (no LLM, no verification). This
drainer promotes those nodes into the `observations` table where the verify
pipeline, gap_sweep and Metabase can all see them, carrying agent provenance.

Properties:
  * idempotent — re-running never double-inserts (keyed on node_id + claim hash)
  * deduped — identical claim text from two agents collapses to one observation
  * non-destructive — nodes are never mutated, only read
  * verification_status='unverified' — extract/verify can promote them later

Run: python3 scripts/observe_drain.py [--dry-run] [--container saimon-postgres]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

CONTAINER_DEFAULT = "saimon-postgres"

# Normalised claim hash: trim, collapse whitespace, lowercase.
CLAIM_HASH = "md5(lower(regexp_replace(btrim(n.body), '\\s+', ' ', 'g')))"

DRAIN_SQL = f"""
WITH candidates AS (
    SELECT
        n.id,
        btrim(n.body)                                   AS claim_text,
        COALESCE(NULLIF(n.metadata->>'topic', ''), 'uncategorised') AS topic,
        LEFT(btrim(n.body), 200)                        AS summary,
        COALESCE(NULLIF(n.metadata->>'confidence', '')::float8, 0.5) AS confidence,
        n.title                                         AS rationale,
        {CLAIM_HASH}                                    AS claim_hash,
        n.metadata,
        n.created_at
    FROM knowledge_graph_nodes n
    WHERE n.content_type = 'observation'
      AND btrim(COALESCE(n.body, '')) <> ''
      AND NOT EXISTS (
            SELECT 1 FROM observations o
             WHERE o.metadata->>'node_id' = n.id::text
      )
      AND NOT EXISTS (
            SELECT 1 FROM observations o
             WHERE o.metadata->>'claim_hash' = {CLAIM_HASH}
      )
),
ins AS (
    INSERT INTO observations
        (claim_text, topic, summary, confidence_0_1, rationale,
         source_text_hash, verification_status, metadata)
    SELECT
        c.claim_text,
        c.topic,
        c.summary,
        LEAST(GREATEST(c.confidence, 0.0), 1.0),
        c.rationale,
        LEFT(c.claim_hash, 16),
        'unverified',
        c.metadata || jsonb_build_object(
            'source',        'agent_observation',
            'node_id',       c.id::text,
            'claim_hash',    c.claim_hash,
            'agent',         COALESCE(NULLIF(c.metadata->>'agent', ''), 'unknown'),
            'captured_at',   to_jsonb(c.created_at)
        )
    FROM candidates c
    RETURNING id, topic, metadata->>'agent' AS agent
)
SELECT (SELECT count(*) FROM candidates) AS candidates,
       (SELECT count(*) FROM ins)        AS inserted,
       (SELECT count(*) FROM knowledge_graph_nodes
         WHERE content_type = 'observation') AS observation_nodes_total,
       (SELECT count(*) FROM observations) AS observations_total;
"""

DRY_RUN_SQL = f"""
SELECT count(*) AS would_insert
FROM knowledge_graph_nodes n
WHERE n.content_type = 'observation'
  AND btrim(COALESCE(n.body, '')) <> ''
  AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.metadata->>'node_id' = n.id::text)
  AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.metadata->>'claim_hash' = {CLAIM_HASH});
"""


def run_sql(sql: str, container: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", "-i", container,
         "psql", "-U", "saimon", "-d", "saimon", "-v", "ON_ERROR_STOP=1", "-At", "-F", ",", "-c", sql],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"drain failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing when zero observations were inserted (cron mode)")
    ap.add_argument("--container", default=CONTAINER_DEFAULT)
    args = ap.parse_args()

    out = run_sql(DRY_RUN_SQL if args.dry_run else DRAIN_SQL, args.container)
    if args.quiet and not args.dry_run and out.split(",")[1:2] == ["0"]:
        return 0
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
