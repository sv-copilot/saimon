-- Saimon Platform — PostgreSQL 16 schema
-- Initialized automatically by docker-compose on first run.
-- The platform should survive a DB wipe and re-seed from seed_requests.

-- ---------------------------------------------------------------------------
-- extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;

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
-- sources — registered data source indexes (shadow libraries, web, KG)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id              SERIAL PRIMARY KEY,
    type            TEXT NOT NULL,                    -- 'shadow_library', 'knowledge_graph', 'web_page'
    identifier      TEXT NOT NULL UNIQUE,             -- e.g. 'annas_archive', 'libgen', 'scihub'
    label           TEXT NOT NULL,                    -- human-readable label
    tier            TEXT NOT NULL DEFAULT 'B',        -- S, A, B, C (reliability tier)
    status          TEXT NOT NULL DEFAULT 'active',   -- active, degraded, disabled
    description     TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_type
    ON sources(type);

-- Seed default sources
INSERT INTO sources (type, identifier, label, tier, description)
VALUES
    ('knowledge_graph', 'kg-root',     'Knowledge Graph Root',        'S', 'Root node of the knowledge graph'),
    ('knowledge_graph', 'kg-concepts', 'Knowledge Graph Concepts',    'S', 'Concept nodes in the knowledge graph'),
    ('web_page',        'web-index',   'Web Index',                   'A', 'General web search index'),
    ('shadow_library',  'annas_archive','Anna''s Archive',            'S', 'The largest open-source shadow library'),
    ('shadow_library',  'libgen',      'Library Genesis (LibGen)',    'S', 'Scientific articles and books'),
    ('shadow_library',  'scihub',      'Sci-Hub / SciDB',             'S', 'Paywalled academic paper access'),
    ('shadow_library',  'academic_torrents', 'Academic Torrents',     'A', 'Bulk academic dataset torrents'),
    ('shadow_library',  'internet_archive',  'Internet Archive',      'A', 'Digital library with books, papers, and web archives')
ON CONFLICT (identifier) DO NOTHING;

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
    user_id         UUID REFERENCES users(id),     -- NULL = shared/public content
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
-- shadow_sources_cache — cached shadow library metadata (DOI → paper)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shadow_sources_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doi             TEXT NOT NULL UNIQUE,               -- canonical DOI (lowercased, stripped)
    title           TEXT NOT NULL,
    authors         JSONB NOT NULL DEFAULT '[]',
    year            INT,
    abstract_snippet TEXT,
    source_index     TEXT NOT NULL,                      -- which adapter resolved it
    file_type       TEXT,                                -- 'pdf', 'epub', 'djvu'
    full_text_path  TEXT,                                -- path to cached passage / PDF
    metadata        JSONB NOT NULL DEFAULT '{}',
    last_accessed   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shadow_cache_doi
    ON shadow_sources_cache(doi);
CREATE INDEX IF NOT EXISTS idx_shadow_cache_last_accessed
    ON shadow_sources_cache(last_accessed DESC);

-- ---------------------------------------------------------------------------
-- seed data — bootstraps the platform with content types, voice profiles,
-- and seed requests for platform recovery.
-- ---------------------------------------------------------------------------

-- Content types (bootstrapped + domain)
INSERT INTO content_type_registry (name, description, required_params, optional_params, voice_profile)
VALUES
    ('blog_post',     'Long-form blog article with introduction, body, and conclusion.',
     '[{"name":"prompt","type":"str","description":"The topic or writing prompt."}]',
     '[{"name":"tone","type":"str","description":"Desired tone (e.g. analytical, casual)."},{"name":"max_length","type":"int","description":"Maximum word count."},{"name":"audience","type":"str","description":"Target audience description."}]',
     'spencer-default'),
    ('summary',       'Concise summary of source material.',
     '[{"name":"prompt","type":"str","description":"The material to summarise."}]',
     '[{"name":"max_length","type":"int","description":"Maximum word count for the summary."},{"name":"style","type":"str","description":"Summary style (e.g. bullet, paragraph)."}]',
     'spencer-default'),
    ('research_note', 'Structured research note with citations.',
     '[{"name":"prompt","type":"str","description":"The research question or topic."}]',
     '[{"name":"tone","type":"str","description":"Desired tone."},{"name":"depth","type":"str","description":"Depth level: brief, standard, comprehensive."},{"name":"format","type":"str","description":"Output format: markdown, outline, bullets."}]',
     'spencer-technical'),
    ('social_post',   'Short-form social media post.',
     '[{"name":"prompt","type":"str","description":"The topic or announcement."}]',
     '[{"name":"platform","type":"str","description":"Target platform: twitter, linkedin, mastodon."},{"name":"tone","type":"str","description":"Desired tone."},{"name":"max_length","type":"int","description":"Maximum character count."}]',
     'spencer-casual'),
    ('email_draft',   'Polished email draft.',
     '[{"name":"prompt","type":"str","description":"The email topic or intent."}]',
     '[{"name":"tone","type":"str","description":"Desired tone."},{"name":"recipient_role","type":"str","description":"Role of recipient (e.g. manager, client)."}]',
     'spencer-default'),
    ('press_release', 'Formal press release announcing news or a product launch.',
     '[{"name":"prompt","type":"str","description":"The announcement topic."}]',
     '[{"name":"embargo_date","type":"str","description":"ISO date before which the release is embargoed."},{"name":"distribution","type":"str","description":"Distribution channel: wire, blog, email."},{"name":"tone","type":"str","description":"Desired tone."}]',
     'spencer-formal'),
    ('case_study',    'Customer or project case study with problem, solution, and results.',
     '[{"name":"prompt","type":"str","description":"The case study topic or subject."}]',
     '[{"name":"industry","type":"str","description":"Industry vertical."},{"name":"format","type":"str","description":"Output format: narrative, slides, one-pager."},{"name":"tone","type":"str","description":"Desired tone."}]',
     'spencer-marketing'),
    ('white_paper',   'In-depth white paper on a technical or strategic topic.',
     '[{"name":"prompt","type":"str","description":"The white paper topic."}]',
     '[{"name":"audience","type":"str","description":"Target audience: technical, executive, general."},{"name":"depth","type":"str","description":"Depth: overview, detailed, comprehensive."},{"name":"tone","type":"str","description":"Desired tone."},{"name":"sections","type":"list[str]","description":"Requested section titles."}]',
     'spencer-technical'),
    ('job_posting',   'Job posting with role description, qualifications, and responsibilities.',
     '[{"name":"prompt","type":"str","description":"The role title and brief description."}]',
     '[{"name":"role","type":"str","description":"Specific role title."},{"name":"company","type":"str","description":"Company name."},{"name":"seniority","type":"str","description":"Seniority level: junior, mid, senior, lead."}]',
     'spencer-formal'),
    ('meeting_notes', 'Structured meeting notes with agenda, discussion points, and action items.',
     '[{"name":"prompt","type":"str","description":"The meeting topic or raw transcription."}]',
     '[{"name":"attendees","type":"list[str]","description":"List of attendee names."},{"name":"format","type":"str","description":"Output format: bullet, narrative, template."},{"name":"action_items","type":"bool","description":"Whether to extract and list action items."}]',
     'spencer-default'),
    ('proposal',      'Business or project proposal with executive summary, scope, timeline, and budget.',
     '[{"name":"prompt","type":"str","description":"The proposal topic or RFP description."}]',
     '[{"name":"client","type":"str","description":"Client or stakeholder name."},{"name":"budget","type":"str","description":"Budget range or constraints."},{"name":"timeline","type":"str","description":"Project timeline."},{"name":"format","type":"str","description":"Output format: brief, full, slides."}]',
     'spencer-formal'),
    ('tutorial',      'Step-by-step tutorial or how-to guide.',
     '[{"name":"prompt","type":"str","description":"The tutorial topic."}]',
     '[{"name":"skill_level","type":"str","description":"Target skill level: beginner, intermediate, advanced."},{"name":"format","type":"str","description":"Output format: markdown, notebook, video script."},{"name":"prerequisites","type":"list[str]","description":"Required knowledge or tools."}]',
     'spencer-technical'),
    ('product_review','Structured product or service review with pros, cons, and rating.',
     '[{"name":"prompt","type":"str","description":"The product or service to review."}]',
     '[{"name":"rating_scale","type":"str","description":"Rating scale: 5-star, 10-point, letter."},{"name":"pros_cons","type":"bool","description":"Whether to include pros/cons list."},{"name":"tone","type":"str","description":"Desired tone."}]',
     'spencer-technical'),
    ('bibliography',  'Ranked, annotated bibliography with DOIs and source index attribution.',
     '[{"name":"prompt","type":"str","description":"The research topic or question."}]',
     '[{"name":"source_indexes","type":"list[str]","description":"Shadow library source indexes to search."},{"name":"limit","type":"int","description":"Maximum number of entries."},{"name":"annotation_style","type":"str","description":"Annotation style: descriptive, evaluative, combined."},{"name":"tone","type":"str","description":"Desired tone."}]',
     'spencer-technical')
ON CONFLICT (name) DO NOTHING;

-- Voice profiles
INSERT INTO voice_profiles (name, description, tone, style_guide)
VALUES
    ('spencer-default', 'Default Spencer Varadi voice: direct, analytical, slightly informal.',
     'analytical',
     'Use short paragraphs. Prefer active voice. Be direct but not blunt. Use bullet points for lists.'),
    ('spencer-formal', 'Formal Spencer voice: polished, diplomatic, suitable for executive audiences.',
     'formal',
     'Use proper grammar and full sentences. Avoid contractions. Maintain a diplomatic tone. Structure with clear headings. Include executive summary for long documents.'),
    ('spencer-casual', 'Casual Spencer voice: friendly, approachable, conversational.',
     'casual',
     'Write like you are talking to a colleague. Use contractions freely. Keep sentences short and punchy. Use em-dashes for asides. One idea per paragraph.'),
    ('spencer-marketing', 'Marketing Spencer voice: persuasive, benefit-focused, engaging.',
     'persuasive',
     'Lead with benefits, not features. Use social proof where possible. Keep the reader moving with short paragraphs and compelling transitions. Include a clear call to action.'),
    ('spencer-technical', 'Technical Spencer voice: precise, detailed, assumes domain knowledge.',
     'technical',
     'Be precise with terminology. Define acronyms on first use. Use code blocks and diagrams where appropriate. Cite sources. Prioritise accuracy over brevity.')
ON CONFLICT (name) DO NOTHING;

-- Seed requests for platform recovery / re-seeding
INSERT INTO seed_requests (content_type, prompt, parameters)
VALUES
    ('blog_post',     'The future of AI agents in personal productivity: how autonomous agents will reshape daily workflows by 2030.',
                      '{"tone":"analytical","audience":"tech professionals"}'),
    ('blog_post',     'Lessons learned from building six microservices that share one knowledge graph.',
                      '{"tone":"casual","max_length":1200}'),
    ('summary',       'Summarise the Saimon platform architecture: six atomic MCP services (search, generate, export, evaluate, verify, explore) sharing one PostgreSQL knowledge graph with runtime content type registration.',
                      '{"style":"bullet","max_length":150}'),
    ('research_note', 'Retrieval-augmented generation (RAG): how grounding LLM outputs in a knowledge graph improves factuality and reduces hallucination.',
                      '{"depth":"comprehensive","format":"markdown"}'),
    ('social_post',   'Announce Saimon v1.0: an open-source, self-extending content platform powered by six MCPs and one knowledge graph. Built for agents, by agents.',
                      '{"platform":"linkedin","tone":"casual"}'),
    ('social_post',   'Hot take: the best AI tools are the ones that know when to stay out of your way. Saimon is designed around this principle.',
                      '{"platform":"twitter","max_length":280}'),
    ('email_draft',   'Invite the engineering team to adopt AI-assisted development workflows using Saimon''s MCP tools.',
                      '{"tone":"casual","recipient_role":"engineering team"}'),
    ('press_release', 'Saimon launches as open-source self-extending content platform: six MCPs, one knowledge graph, runtime type registration.',
                      '{"tone":"formal","distribution":"wire"}'),
    ('case_study',    'How a research team reduced content creation time by 60% after adopting Saimon for automated research notes and summaries.',
                      '{"industry":"technology","format":"narrative"}'),
    ('white_paper',   'The case for self-extending AI platforms: why static content pipelines fail and how runtime type registration solves the adaptability problem.',
                      '{"audience":"technical","depth":"comprehensive"}'),
    ('job_posting',   'Senior Python Engineer — help us build the future of AI-assisted content tooling with FastAPI, PostgreSQL, and MCP.',
                      '{"seniority":"senior"}'),
    ('meeting_notes', 'Weekly engineering sync: reviewed Saimon architecture, discussed self-extension flow, planned domain tools sprint, identified need for seed data module.',
                      '{"format":"bullet","action_items":true}'),
    ('proposal',      'Proposal for implementing AI governance in enterprise content pipelines: audit trails, quality gates, human-in-the-loop review workflows.',
                      '{"format":"brief","timeline":"Q1-Q2 2026"}'),
    ('tutorial',      'Getting started with Saimon: build and register your first custom content type in 10 minutes.',
                      '{"skill_level":"beginner","format":"markdown"}'),
    ('product_review','Review of Saimon v1.0 as a content generation platform: architecture, extensibility, developer experience, and limitations.',
                      '{"rating_scale":"5-star","pros_cons":true}')
ON CONFLICT DO NOTHING;
