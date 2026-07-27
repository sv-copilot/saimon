-- Saimon Platform — PostgreSQL 16 schema
-- Initialized automatically by docker-compose on first run.
-- The platform should survive a DB wipe and re-seed from seed_requests.

-- ---------------------------------------------------------------------------
-- content_type_registry — extensible content type definitions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_type_registry (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    required_params JSONB NOT NULL DEFAULT '[]',
    optional_params JSONB NOT NULL DEFAULT '[]',
    voice_profile   TEXT,                          -- e.g. 'spencer-default'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- knowledge_graph_nodes — the core graph entity
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_graph_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    content_type    TEXT NOT NULL REFERENCES content_type_registry(name),
    body            TEXT NOT NULL DEFAULT '',
    metadata        JSONB NOT NULL DEFAULT '{}',
    embedding       VECTOR(1536),                  -- pgvector extension required
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_content_type
    ON knowledge_graph_nodes(content_type);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_created_at
    ON knowledge_graph_nodes(created_at DESC);

-- ---------------------------------------------------------------------------
-- knowledge_graph_edges — relationships between nodes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES knowledge_graph_nodes(id) ON DELETE CASCADE,
    target_id       UUID NOT NULL REFERENCES knowledge_graph_nodes(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,                  -- e.g. 'cites', 'supports', 'contradicts'
    weight          REAL NOT NULL DEFAULT 1.0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_id, target_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_kg_edges_source
    ON knowledge_graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target
    ON knowledge_graph_edges(target_id);

-- ---------------------------------------------------------------------------
-- seed_requests — platform recovery / re-seed source
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seed_requests (
    id              SERIAL PRIMARY KEY,
    content_type    TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    parameters      JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending', -- pending, in_progress, complete, failed
    result_id       UUID REFERENCES knowledge_graph_nodes(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_seed_requests_status
    ON seed_requests(status);

-- ---------------------------------------------------------------------------
-- voice_profiles — tone/style presets for content generation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS voice_profiles (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    tone            TEXT NOT NULL DEFAULT 'neutral',
    style_guide     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- audit_log — structured audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        TEXT NOT NULL,
    service_name    TEXT NOT NULL,
    event_type      TEXT NOT NULL,                   -- 'request', 'response', 'error'
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_trace_id
    ON audit_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_service
    ON audit_log(service_name, created_at DESC);

-- ---------------------------------------------------------------------------
-- seed data — bootstraps the platform with default content types
-- ---------------------------------------------------------------------------
INSERT INTO content_type_registry (name, description, required_params, optional_params)
VALUES
    ('blog_post',     'Long-form blog article with introduction, body, and conclusion.',  '["prompt"]', '["tone", "max_length", "audience"]'),
    ('summary',       'Concise summary of source material.',                               '["prompt"]', '["max_length", "style"]'),
    ('research_note', 'Structured research note with citations.',                          '["prompt"]', '["tone", "depth", "format"]'),
    ('social_post',   'Short-form social media post.',                                    '["prompt"]', '["platform", "tone", "max_length"]'),
    ('email_draft',   'Polished email draft.',                                            '["prompt"]', '["tone", "recipient_role"]')
ON CONFLICT (name) DO NOTHING;

INSERT INTO voice_profiles (name, description, tone, style_guide)
VALUES
    ('spencer-default', 'Default Spencer Varadi voice: direct, analytical, slightly informal.',
     'analytical',
     'Use short paragraphs. Prefer active voice. Be direct but not blunt. Use bullet points for lists.')
ON CONFLICT (name) DO NOTHING;
