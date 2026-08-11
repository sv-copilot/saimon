# Saimon Platform

A self-extending platform of 6 atomic MCP services sharing one PostgreSQL
knowledge graph. Built for AI agents, by AI agents.

## What It Does

Saimon gives AI coding agents research superpowers: search academic shadow
libraries, verify factual claims, generate cited content, and persist
everything to a knowledge graph.

```
Ask a question → Search 5 shadow libraries → Verify against sources
→ Generate cited report → Evaluate quality → Export formatted output
```

## Architecture

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  SEARCH  │ │ GENERATE │ │  EXPORT  │ │ EVALUATE │ │  VERIFY  │ │ EXPLORE  │
│  :8001   │ │  :8002   │ │  :8003   │ │  :8004   │ │  :8005   │ │  :8006   │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │            │            │            │            │
     └────────────┴────────────┴────────────┴────────────┴────────────┘
                                    │
                            ┌───────┴───────┐
                            │  PostgreSQL 16│
                            │  + pgvector   │
                            │  :5432/5433   │
                            └───────────────┘
```

**6 MCPs, 24+ tools, 1 knowledge graph, 0 external dependencies** (beyond DeepSeek LLM).

## Quick Start

### Local Development

```bash
# Clone and start
git clone https://github.com/sv-copilot/saimon.git
cd saimon
docker compose up -d

# Verify
curl http://localhost:8001/health
# → {"status":"ok","service":"search-mcp","checks":{"database":"connected"}}

# Search shadow libraries
curl -X POST http://localhost:8001/tools/search_shadow_libraries \
  -H "X-Saimon-API-Key: sk-test-search-key" \
  -H "Content-Type: application/json" \
  -d '{"trace_id":"00000000-0000-0000-0000-000000000001","content_type":"search","parameters":{"query":"transformer attention mechanisms"}}'
```

### VS Code Integration

The Researcher agent is pre-configured in `.vscode/mcp.json`. Reload VS Code,
select **Researcher** from the agent picker, and ask research questions.

### Staging

Staging runs on a Hetzner CX22 VPS at `mcp-staging.spencervaradi.com`.

## Services

| Service | Port | Tools | Description |
|---|---|---|---|
| search-mcp | 8001 | 5 | Knowledge graph + shadow library search |
| generate-mcp | 8002 | 5 | LLM content generation (14 content types) |
| export-mcp | 8003 | 3 | Output formatting (markdown, json, html) |
| evaluate-mcp | 8004 | 3 | Quality scoring against criteria |
| verify-mcp | 8005 | 3 | Fact-checking with 5 corroboration methods |
| explore-mcp | 8006 | 5 | Knowledge graph discovery and browsing |

## Content Types

Saimon generates 14 content types with 5 voice profiles:

`blog_post` `summary` `research_note` `social_post` `email_draft`
`press_release` `case_study` `white_paper` `job_posting` `meeting_notes`
`proposal` `tutorial` `product_review` `bibliography`

## Testing

```bash
python3 -m pytest tests/ -q          # 616 tests
ruff check research_shared/ mcp/     # Lint
python3 -m compileall research_shared/ mcp/  # Compile check
```

## Documentation

- [Agent Usage Guide](docs/agent-usage-guide.md) — How AI agents should use Saimon
- [AGENTS.md](AGENTS.md) — Development contract and slice governance
- [Staging Deployment](docs/staging.md) — VPS setup and operations

## License

MIT
