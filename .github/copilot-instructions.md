# Saimon Workspace Instructions

This is the Saimon Platform repository — a self-extending platform of 6 MCP
services sharing one PostgreSQL knowledge graph.

## Research

When asked to research, verify, or find sources, use the Researcher agent
(select from agent picker) which has access to 11 Saimon MCP tools:
- `saimon_search_scholarly` — shadow library search
- `saimon_verify_claim` — fact-checking with DeepSeek
- `saimon_generate_content` — LLM content generation
- And 8 more (see `.github/agents/researcher.agent.md`)

## Development

Follow the AGENTS.md contract for slice-based development:
- Branch from `ai-dev` as `slice/NAME`
- TDD: RED → GREEN → REFACTOR → PROVE
- Pre-PR: `python3 -m pytest tests/ -q && ruff check research_shared/ mcp/`
- Squash-merge to `ai-dev`

## Architecture

- `research_shared/` — shared library (envelope, llm, db, auth, audit, lifespan, etc.)
- `mcp/search/` through `mcp/explore/` — 6 MCP FastAPI servers
- `tools/saimon-mcp-proxy/` — MCP JSON-RPC proxy for VS Code integration
- `schema.sql` — PostgreSQL schema with pgvector
- `.github/agents/` — Custom agent definitions

## Services

All 6 MCPs run on ports 8001–8006 locally, 8101–8106 on staging.
PostgreSQL on 5432 (local) or 5433 (staging, to avoid cockpit-postgres conflict).
