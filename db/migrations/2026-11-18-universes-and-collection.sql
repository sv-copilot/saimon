-- Schema catch-up for a database initialised before universes and collection existed.
--
-- Staging was created from an older schema.sql: knowledge_graph_nodes had no
-- `collection` or `universe_id`, and the universes, observation_facts and
-- verification_ledger tables were absent. The ingest tool writes `collection`,
-- so it failed with "column collection does not exist" until this ran.
--
-- Idempotent: safe to apply to a database that already has these objects.

BEGIN;

CREATE TABLE IF NOT EXISTS public.universes (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    parent_id uuid,
    visibility text DEFAULT 'public'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT universes_visibility_check CHECK ((visibility = ANY (ARRAY['public'::text, 'private'::text])))
);

INSERT INTO public.universes (id, slug, name, visibility) VALUES
 ('00000000-0000-4000-8000-000000000001','reality','Reality','public'),
 ('00000000-0000-4000-8000-000000000002','fiction','Fiction','public'),
 ('00000000-0000-4000-8000-000000000003','personal','Personal','private'),
 ('00000000-0000-4000-8000-000000000004','needle','Needle','public')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.observation_facts (
    node_id uuid NOT NULL,
    value_numeric double precision,
    value_text text,
    unit text,
    date_start date,
    date_end date,
    date_base_unit text,
    latitude double precision,
    longitude double precision,
    topic text,
    confidence real DEFAULT 0.0 NOT NULL,
    reasons jsonb DEFAULT '{}'::jsonb NOT NULL,
    parser_version text DEFAULT 'v1'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT observation_facts_date_base_unit_check CHECK ((date_base_unit = ANY (ARRAY['year'::text, 'quarter'::text, 'month'::text, 'day'::text])))
);

CREATE TABLE IF NOT EXISTS public.verification_ledger (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    claim_hash text NOT NULL,
    claim_text text NOT NULL,
    verdict text NOT NULL,
    confidence real NOT NULL,
    method text NOT NULL,
    version text NOT NULL,
    evidence_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    locators text[] DEFAULT '{}'::text[] NOT NULL,
    evidence_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE public.knowledge_graph_nodes
  ADD COLUMN IF NOT EXISTS collection text DEFAULT 'research'::text NOT NULL,
  ADD COLUMN IF NOT EXISTS unit_id uuid,
  ADD COLUMN IF NOT EXISTS universe_id uuid DEFAULT '00000000-0000-4000-8000-000000000001'::uuid;

ALTER TABLE public.observations
  ADD COLUMN IF NOT EXISTS collection text DEFAULT 'research'::text NOT NULL,
  ADD COLUMN IF NOT EXISTS unit_id uuid,
  ADD COLUMN IF NOT EXISTS universe_id uuid;

CREATE INDEX IF NOT EXISTS knowledge_graph_nodes_collection_idx ON public.knowledge_graph_nodes (collection);
CREATE INDEX IF NOT EXISTS knowledge_graph_nodes_universe_idx ON public.knowledge_graph_nodes (universe_id);

-- Grants only where the role exists: on a fresh database the per-service roles
-- are created by db/init-roles.sh at container init, which has not run when a
-- migration applies to a bare schema.
DO $$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['api_mcp','search_mcp','generate_mcp','export_mcp',
                                     'evaluate_mcp','verify_mcp','explore_mcp','domain_mcp','crew_mcp']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', role_name);
        END IF;
    END LOOP;
END $$;

COMMIT;
