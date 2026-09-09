-- Metabase provisioning (one-time, run as superuser on saimon-postgres).
-- Substitutes: __METABASE_DB_PASSWORD__ and __METABASE_RO_PASSWORD__.

-- 1. Metabase's own metadata database + user (owns its app DB)
CREATE DATABASE metabase;
CREATE USER metabase WITH PASSWORD '__METABASE_DB_PASSWORD__';
GRANT ALL PRIVILEGES ON DATABASE metabase TO metabase;
ALTER DATABASE metabase OWNER TO metabase;

-- 2. Read-only role for the saimon data — all three planes
--    (relational, knowledge graph, RAG/audit). SELECT-only, no write path.
CREATE USER metabase_ro WITH PASSWORD '__METABASE_RO_PASSWORD__';
GRANT CONNECT ON DATABASE saimon TO metabase_ro;
GRANT USAGE ON SCHEMA public TO metabase_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO metabase_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO metabase_ro;
