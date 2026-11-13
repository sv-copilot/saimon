# Saimon

A verification-first knowledge base for AI agents: nine MCP services over one
PostgreSQL graph with pgvector.

The problem it solves is not retrieval. It is that an agent will state anything in
confident prose. Saimon stores what was claimed, what evidence exists, where that
evidence came from, and — most importantly — **refuses to answer when the evidence is
thin**.

## What makes it different

- **It abstains by default.** A query that finds nothing strong returns `results: []`
  with a reason (`floor`, `margin`, `no_lexical_support`), not the nearest five chunks.
  An empty *success* means "the corpus does not support this"; an empty *degraded*
  means "the service is down". Those are different facts and the API keeps them apart.
- **Every claim carries a verdict.** Claims are verified against stored passages and
  written to an append-only ledger: `supported`, `contradicted`, or
  `insufficient_evidence`. Nothing becomes fact because it was generated fluently.
- **Provenance is a first-class field.** Citations carry a DOI/URL locator or a stated
  reason there is none, plus a primacy tier. A citation without a locator is a lead,
  not a fact.
- **Scopes are enforced, not suggested.** Content lives in a universe (`reality`,
  `fiction`, `personal`); retrieval resolves the caller's scope and filters before
  ranking. A private universe with no owner returns an empty scope — a refusal, not a
  fallback to public data.
- **Retrieval is fused and measured.** Vector and lexical candidates are merged with
  reciprocal rank fusion, reranked, then gated. A golden evaluation harness and a
  perturbation test fail the build if a known query changes verdict.

## Architecture

```
 search  generate  export  evaluate  verify  explore  api  domain  crew
 :8001    :8002    :8003    :8004     :8005   :8006   :8007 :8008   :8009
   └────────┴────────┴────────┴─────────┴───────┴───────┴──────┴───────┘
                                   │
                        ┌──────────┴──────────┐
                        │   PostgreSQL 16     │
                        │   + pgvector        │
                        │   knowledge graph   │
                        └─────────────────────┘
```

Every service holds its own asyncpg pool and speaks HTTP. There is no message bus and
no second datastore — the graph is the only state.

| Service | Port | Tools | Responsibility |
|---|---|---|---|
| `search` | 8001 | 11 | graph search, web search, document ingest, source registry |
| `generate` | 8002 | 9 | content generation, verified generation, `store_content` |
| `export` | 8003 | 3 | format conversion |
| `evaluate` | 8004 | 4 | quality scoring, AI-text detection, voice profiles |
| `verify` | 8005 | 5 | claim verification against the corpus, claim extraction |
| `explore` | 8006 | 6 | typed traversal, connection discovery, content browsing |
| `api` | 8007 | — | OpenAPI documentation gateway |
| `domain` | 8008 | 6 | plugin surface for domain-specific tools |
| `crew` | 8009 | 2 | background research and claim extraction jobs |

## Quick start

```bash
git clone https://github.com/sv-copilot/saimon.git
cd saimon
cp .env.example .env          # set the values marked REQUIRED
docker compose up -d
curl -s localhost:8001/health
```

The database passwords have no defaults: `POSTGRES_PASSWORD` and the nine
`*_DB_PASSWORD` values must be set in `.env` before `docker compose up`, or the
services start with empty passwords and fail to authenticate.

The stack needs PostgreSQL with `pgvector` (included in the compose file) and one LLM
API key for generation and verification. Embeddings, retrieval and verification run
locally.

Each service authenticates with `X-Saimon-API-Key`. The value may be a comma-separated
list, so several agents can share a service while staying distinguishable in the audit
log.

```bash
curl -s -X POST localhost:8001/tools/search_knowledge_graph \
  -H "X-Saimon-API-Key: $SAIMON_SEARCH_KEY" \
  -H "Content-Type: application/json" \
  -d '{"trace_id":"3f6c1a1e-0000-4000-8000-000000000001",
       "content_type":"search",
       "parameters":{"query":"vector index tuning","limit":3}}'
```

## The retrieval contract

This is the part worth reading if you are evaluating the design.

```jsonc
// answer found
{"status": "success", "data": {"results": [...], "total": 3}}

// corpus has nothing strong enough — an answer, not an error
{"status": "success", "data": {"results": [], "total": 0,
 "no_strong_evidence": true, "abstain_reason": "margin"}}

// service unreachable — an outage, not an absence
{"status": "degraded", "data": {"results": [], "reason": "knowledge graph unavailable"}}
```

A degraded response returns **no rows**. An earlier version returned synthetic
placeholder results so a demo would look alive; that is worse than failing, because a
fabricated row is indistinguishable from a real one once it leaves the service.

## Testing

```bash
pytest -q          # ~2,000 tests, no external services required
ruff check .
```

The suite runs against fakes: no database, no network, no API keys. Live behaviour is
covered separately by a golden evaluation harness (`scripts/eval_golden.py`) and a
retrieval-stability check (`scripts/retrieval_stability.py`).

## Scope and limitations

- **Lawful sources only.** An earlier development line included adapters for Sci-Hub,
  LibGen and Anna's Archive. The adapter code was **removed from the tree in #321**
  (2026-11-12); the commits that added it remain in the repository's history, so a
  reader of the history can still find them. Shipping scrapers for those services is
  not something this project should do, and a knowledge base whose evidence cannot be
  cited lawfully is not a knowledge base. The supported path is lawful sources —
  OpenAlex, Crossref, arXiv, the Internet Archive, and PDFs you are entitled to read.
- **Naming debt.** A few identifiers from that line survive — a DOI cache table named
  `shadow_sources_cache`, an evidence type `shadow_source`, and a stored response key.
  They are historical names for a lawful full-text cache, and renaming them needs a
  production migration; the code that would fetch from those services is gone.
- **Single node by design.** One Postgres, one host. It is not a distributed system and
  does not pretend to be.
- **No bundled model.** Generation and verification call an LLM API; retrieval,
  embedding and the graph are local.
- **Not a document manager.** Ingest is by URL or supplied text, behind a quality gate.

## Documentation

- [AGENTS.md](AGENTS.md) — development contract and slice governance
- `docs/` — schema notes, operational runbooks

## License

Apache-2.0. See [LICENSE](LICENSE).
