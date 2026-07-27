# AGENTS.md

Operating contract for AI agents working in a **Drake** governance repository.

Drake provides repository-native governance for AI-assisted development: slice
planning, dependency graphs, adapter contracts, and validation tooling.

## Project Context

Saimon is a self-extending platform of 6 atomic MCP services that share one
PostgreSQL knowledge graph. Domain tools (job hunt, writing, research) add
capabilities by registering content types and voice profiles — not by building
new MCPs.

## Branch Policy

- `main` — stable integration branch for adopters.
- `ai-dev` — agent integration branch when using Drake automations.
- `slice/*` — feature branches for isolated slices.

## Validation before PR

From repo root:

```bash
python3 -m pytest tests/ -q
python3 -m compileall research_shared/ mcp/
ruff check research_shared/ mcp/
```

## Scope

- Keep product runtime code in this repository.
- Planning artifacts live in `simon-projects` under `.docs/planning/projects/saimon/`.
- Use `research_shared/` for shared library code (envelope, LLM, DB, auth, resilience, audit).
- Each MCP lives under `mcp/<name>/`.
- Do not commit secrets, API keys, or `.env` files.

## Architecture

- **6 atomic MCPs**: search, generate, export, evaluate, verify, explore
- **Shared PostgreSQL**: all MCPs share one DB; no MCP calls another MCP directly
- **Self-extending**: content types registered at runtime via research-backed flow
- **HTTP/Docker transport**: each MCP runs as a long-running Docker container
- **Fail-closed**: no API key → error. LLM down → degraded response.

## Stack

- Python 3.11+ with FastAPI (HTTP MCP servers)
- PostgreSQL 16 (knowledge graph + extensibility tables)
- Docker (single image, CMD override per MCP)
- DeepSeek (primary LLM) via OpenAI-compatible API

See `docs/getting-started.md` for a minimal adoption path.
