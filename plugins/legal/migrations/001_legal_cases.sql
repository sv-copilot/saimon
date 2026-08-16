-- 001_legal_cases.sql — optional performance table for legal case metadata.
--
-- Materialises frequently queried case fields so citation lookups do not
-- repeatedly scan knowledge_graph_nodes metadata JSONB.  Idempotent: safe to
-- run repeatedly via schema_migrations().

CREATE TABLE IF NOT EXISTS legal_cases (
    id              SERIAL PRIMARY KEY,
    citation_string TEXT NOT NULL UNIQUE,
    court           TEXT,
    jurisdiction    TEXT,
    decided_date    DATE,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_legal_cases_court
    ON legal_cases (court);

CREATE INDEX IF NOT EXISTS idx_legal_cases_jurisdiction
    ON legal_cases (jurisdiction);
