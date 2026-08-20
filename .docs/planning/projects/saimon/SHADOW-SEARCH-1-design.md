# SHADOW-SEARCH-1 — Design Document

**Status:** Design & Assessment (pre-implementation)
**Date:** 2026-07-27
**Author:** AI agent (sv-copilot/saimon)

---

## 1. Terminology Correction

Before we design, we fix the terminology bug identified in the current
codebase:

| Current Name | Corrected Name | Reason |
|---|---|---|
| `list_sources` | `list_source_indexes` | It returns *source indexes* (Anna's Archive, LibGen, KG root), not individual *sources* (papers, articles). A SourceReference in `envelope.py` is a `type + identifier` pair — ONE paper/article. |
| `get_source_detail` | `get_source_index_detail` | Same rationale — the detail endpoint describes a source index, not a single source. |

**Backward compat strategy:** Keep `POST /tools/list_sources` and
`POST /tools/get_source_detail` as aliases that return a deprecation
warning header (`X-Deprecated: true`) and forward to the new endpoints.
Remove after 1 release cycle.

---

## 2. Shadow Library Source Index Catalog

Sourced from https://shadowlibraries.github.io/. Each entry assessed
for search/API feasibility, metadata richness, and trust model.

### 2.1 Direct Downloads

| # | Name | URL | Type | API? | Metadata | Full-text? | Trust | Tier |
|---|---|---|---|---|---|---|---|---|
| 1 | **Anna's Archive** | annas-archive.gl | Metasearch (LibGen + Sci-Hub + Z-Lib + IA) | Unofficial JSON API (torrent metadata, not full search) | DOI, title, author, year, language, filetype, filesize, MD5 | Yes (via SciDB/Sci-Hub redirect) | Algorithmic (aggregates LibGen + Sci-Hub) | **S** |
| 2 | **LibGen** | libgen.li, .vg, .la, .bz, .gl | Direct search | Scrape only (HTML tables, no official API) | DOI, title, author, year, publisher, ISBN, MD5 | Yes (PDF/DjVu downloads) | Community-uploaded + algorithmic | **S** |
| 3 | **Sci-Hub / SciDB** | sci-hub.st, annas-archive.gd/scidb/ | DOI proxy (Sci-Hub paused uploading new papers since 2021) | SciDB via Anna's Archive has search | DOI, title, author, journal, year | Yes (direct PDF view) | Bot-harvested via institutional proxies | **S** |
| 4 | **Nexus/Library** | libstc.nexus | Sci-Hub successor w/ search | Possibly (undocumented) | DOI, title, metadata | Yes | Community / bot-harvested | **A** |
| 5 | **Sci-Net** | sci-net.xyz | Community-curated DB | Unknown | Title, author, abstract likely | Likely yes | Community-curated | **A** |
| 6 | **Internet Archive** | archive.org | General digital library | Yes (archive.org API + Open Library API) | Title, author, year, publisher, description, collections | Yes (for many items) | Institutional preservation | **A** |
| 7 | **Memory of the World** | memoryoftheworld.org | Thematic collections (activist, art, theory) | No (browse-only) | Title, author, collection theme | Yes (PDF downloads) | Community-curated | **B** |
| 8 | **r/Scholar** | reddit.com/r/Scholar | Request-fulfillment (users post DOI, others fetch) | Pushshift/Reddit API (historical) | DOI in post title; no structured metadata | Indirect (user DMs PDF) | Community peer-to-peer | **C** |
| 9 | Lectulandia | (Spanish) | Ebooks | No | Title, author | Yes | Community | **D** |
| 10 | Ebiblioteca | (Spanish) | Ebooks | No | Title, author | Yes | Community | **D** |
| 11 | Epubera | (Spanish) | Ebooks | No | Title, author | Yes | Community | **D** |
| 12 | Ebookelo | (various) | Ebooks | No | Title, author | Yes | Community | **D** |
| 13 | Rave Book Search | (various) | Ebook search | Scrape | Title | Yes | Algorithmic | **D** |

### 2.2 Torrents

| # | Name | URL | Type | API? | Metadata | Full-text? | Trust | Tier |
|---|---|---|---|---|---|---|---|---|
| 14 | **Academic Torrents** | academictorrents.com | Dataset/paper torrents | Yes (REST API) | Title, author, DOI, category, description, filesize | Yes (entire datasets) | Community-uploaded, moderator-reviewed | **A** |
| 15 | Epublibre | (Spanish) | Ebook torrents | No | Title, author | Yes | Community | **D** |
| 16 | Torrent packs | (various) | Bulk ebook packs | No | Minimal (pack name only) | Yes but unstructured | Community | **D** |

### 2.3 Live Channels

| # | Name | URL | Type | API? | Metadata | Full-text? | Trust | Tier |
|---|---|---|---|---|---|---|---|---|
| 17 | IRC #bookz | irc.undernet.org #bookz | IRC XDCC bot | IRC protocol (automate-able) | Filename-based only | Yes (XDCC downloads) | Community peer-to-peer | **C** |
| 18 | Telegram @libgen_scihub_bot | t.me/libgen_scihub_bot | Telegram bot | Telegram Bot API (automate-able) | DOI/title search via bot commands | Yes (bot sends PDF) | Bot acts as Sci-Hub/LibGen proxy | **B** |

### 2.4 Tier Legend

| Tier | Definition | Integration Strategy |
|---|---|---|
| **S** | Core source index — high metadata quality, large corpus, searchable | Direct integration in `search_shadow_libraries` |
| **A** | Strong source index — good metadata, searchable, smaller corpus | Included in search, lower default weight |
| **B** | Niche source index — thematic or limited search | Available as optional filter only |
| **C** | Request-fulfillment — no structured search, P2P model | Only as last-resort DOI fulfillment |
| **D** | Excluded — non-English only, no academic focus, or no API | Not integrated (but extensibility point) |

---

## 3. Integration Feasibility Assessment

### 3.1 Tier S — Direct Integration

#### Anna's Archive (S)

- **Search API:** No official public API. Unofficial endpoints exist for
  torrent metadata (JSON via `annas-archive.gl/torrents/...`). The
  primary search interface is HTML pages that can be scraped.
- **Scraping approach:** HTTP GET to `annas-archive.gl/search?q=QUERY`
  → parse HTML results table. Each row yields: title, author, year,
  filetype, language, filesize, MD5 hash. No abstract/snippet.
- **Bulk data:** Anna's Archive publishes periodic database dumps on
  their torrents page. These can be ingested into the KG for offline
  search — this is the **preferred approach** for Saimon.
- **Metadata quality:** High — aggregates LibGen + Sci-Hub + Z-Library
  metadata. DOIs are present for most academic works.
- **Rate limits:** Aggressive scraping may trigger Cloudflare. Use
  `annas-archive.gl` (`.gl` TLD allows scraping better than `.org`).

#### LibGen (S)

- **Search API:** No official API. Search is via HTML form submission.
  Results are paginated HTML tables.
- **Scraping approach:** POST to `libgen.li/index.php` with `req=QUERY`
  → parse HTML table. Metadata includes: ID, author, title, publisher,
  year, pages, language, size, extension, MD5, direct download links.
- **Database dumps:** LibGen publishes periodic MySQL dumps. These are
  the canonical way to get metadata. Can be imported into PG.
- **Metadata quality:** Good for books; variable for articles (LibGen's
  "scimag" collection is articles, "libgen" is books). DOI coverage is
  spotty compared to Sci-Hub.
- **Rate limits:** 1-2 req/sec recommended. Multiple mirrors available
  for load distribution.

#### Sci-Hub / SciDB (S)

- **Primary use case:** Sci-Hub is a DOI resolver, not a search engine.
  You *must* know the DOI to get a paper. SciDB (via Anna's Archive)
  adds a search layer on top.
- **Search API (SciDB):** SciDB at `annas-archive.gd/scidb/` has its
  own search interface. Scrape HTML results or access via Anna's
  Archive's bulk dumps.
- **DOI resolution:** `sci-hub.ru/DOI_HERE` returns the PDF directly.
  Sci-Hub has paused new paper uploads since 2021 but its existing ~85M
  paper corpus is still accessible.
- **Metadata:** Sci-Hub returns minimal structured metadata (it
  essentially proxies publisher PDFs). DOIs are the key identifier.
- **Integration model:** NOT as a primary search index — use as a
  **resolution layer**: search → get DOI → resolve via Sci-Hub →
  extract passage.

### 3.2 Tier A — Secondary Integration

#### Nexus/Library (A)

- Relatively new Sci-Hub successor. Less mature but has search.
- Feasibility: Medium. Monitor for API stability before deep integration.

#### Sci-Net (A)

- Community-curated database of scientific knowledge.
- Feasibility: Low-Medium. Unknown API surface. Community-driven means
  metadata may be inconsistent.

#### Internet Archive (A)

- **Has a real API.** `archive.org/advancedsearch.php` returns JSON.
  Can query by `collection:(journals)`, `mediatype:(texts)`, and
  full-text metadata.
- Open Library API: `openlibrary.org/search.json?q=QUERY` — returns
  structured JSON with titles, authors, ISBNs, cover images.
- **Metadata:** Excellent. Full bibliographic records.
- **Full-text:** Available for many items via `archive.org/details/ID`.
  OCR text often available.
- **Integration:** Straightforward REST API. Best for books, historical
  documents, and public domain papers.

#### Academic Torrents (A)

- REST API at `academictorrents.com/apiv2/`. Returns JSON.
- Search: `GET /apiv2/search?q=QUERY&field=title&field=description`
- Metadata: title, description, category, DOI, authors list, file
  count, total size, torrent hash, magnet link.
- **Full-text:** Downloadable via torrent, but Saimon would not
  download — it would index metadata only and link to torrent.
- **Integration:** Clean REST API. Good for datasets and paper
  collections.

### 3.3 Tier B — Niche Integration

#### Memory of the World (B)

- No search API. Browse-only by collection theme.
- Feasibility: Low. Would require scraping collection pages and
  building our own index. Better suited as a pre-indexed static
  dataset imported into the KG.
- Value: High for specific domains (critical theory, activist
  literature).

#### Telegram @libgen_scihub_bot (B)

- Telegram Bot API is well-documented. Can send `/search QUERY` to
  the bot and capture response.
- Feasibility: Medium. Requires a Telegram bot account and session
  management. Bot may have rate limits.
- Metadata: Title + download link. Minimal but functional.

### 3.4 Tier C — Last-Resort Fulfillment

#### r/Scholar (C)

- No structured search. Users post `[WANTED] DOI: ...` and others
  reply with PDF links.
- Feasibility: Very low for automated search. Could be used as a
  last-resort DOI fulfillment: if no other source has a paper, post
  a request and poll for responses.
- Not suitable for `search_shadow_libraries`.

#### IRC #bookz (C)

- IRC protocol is automatable (XDCC bots). Search is filename-based
  only.
- Feasibility: Low. Requires persistent IRC connection, channel
  monitoring, and XDCC download automation.
- Not suitable for `search_shadow_libraries`.

---

## 4. `search_shadow_libraries` Tool Design

### 4.1 Tool Registration (search-mcp)

```python
{
    "name": "search_shadow_libraries",
    "description": (
        "Search shadow library source indexes (Anna's Archive, LibGen, "
        "Sci-Hub/SciDB, Internet Archive, Academic Torrents) for "
        "academic papers, books, and datasets. Returns ranked "
        "SourceReferences with DOIs, abstracts, and source index "
        "attribution."
    ),
    "parameters": {
        "query": "str (required)",
        "source_indexes": "list[str] (optional, default: all Tier S + A)",
        "limit": "int (optional, default 10, max 50)",
        "offset": "int (optional, default 0)",
        "sort_by": "str (optional, 'relevance' | 'year' | 'citations', default 'relevance')",
    },
}
```

### 4.2 Endpoint Signature

```
POST /tools/search_shadow_libraries
```

Accepts `ResearchRequest` with:
- `parameters.query` — free-text search query
- `parameters.source_indexes` — optional filter, e.g. `["annas_archive", "libgen", "scihub"]`
- `parameters.limit` — max results
- `parameters.offset` — pagination
- `parameters.sort_by` — ranking strategy

### 4.3 Response Shape

```json
{
  "trace_id": "uuid",
  "status": "success",
  "data": {
    "query": "transformer attention mechanisms survey",
    "total_results": 142,
    "results": [
      {
        "type": "academic_paper",
        "identifier": "doi:10.1038/s41586-023-06004-z",
        "doi": "10.1038/s41586-023-06004-z",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani, A.", "Shazeer, N.", "Parmar, N.", ...],
        "year": 2017,
        "abstract_snippet": "The dominant sequence transduction models are based on...",
        "source_index": "annas_archive",
        "source_index_label": "Anna's Archive",
        "relevance_score": 0.97,
        "full_text_available": true,
        "file_type": "pdf",
        "duplicate_of": null,
        "also_available_at": [
          {"source_index": "libgen", "relevance_score": 0.95},
          {"source_index": "scihub", "relevance_score": null}
        ]
      }
    ]
  },
  "citations": ["doi:10.1038/s41586-023-06004-z", ...],
  "errors": null
}
```

### 4.4 Deduplication Strategy

The same paper exists across Anna's Archive, LibGen, and Sci-Hub.
We deduplicate on DOI (canonical), falling back to title+author
normalization for items without DOIs:

```
1. Group all results by normalized DOI (lowercased, stripped).
2. Within each group, select the "best" result:
   a. Prefer results with abstract_snippet over those without.
   b. Prefer results with verified full_text_available = true.
   c. Merge `also_available_at` to show cross-index availability.
3. For items without DOI: compute normalized title hash + first
   author surname. Group by this key. Flag as `dedup_confidence:
   "medium"` vs `"high"` for DOI-based dedup.
4. Rank deduplicated results by aggregated relevance_score
   (max across source indexes, weighted by source trust tier).
```

### 4.5 Backend Architecture

```
search_shadow_libraries(query, source_indexes, limit)
  │
  ├─► Anna's Archive adapter ──► HTML scrape / bulk DB lookup
  ├─► LibGen adapter         ──► HTML scrape / bulk DB lookup
  ├─► SciDB adapter          ──► Anna's Archive SciDB subset
  ├─► Internet Archive       ──► REST API (archive.org)
  └─► Academic Torrents      ──► REST API (academictorrents.com)
  │
  ▼
  Deduplication Engine ──► ranked SourceReference[]
  │
  ▼
  ResearchResponse
```

Each adapter implements a common interface:

```python
class SourceIndexAdapter(Protocol):
    name: str          # e.g. "annas_archive"
    tier: str          # "S", "A", "B"
    trust_model: str   # "algorithmic" | "community" | "institutional"

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]: ...

    async def resolve_doi(
        self, doi: str
    ) -> SourceSearchResult | None: ...
```

`SourceSearchResult` is a new model in `research_shared/envelope.py`:

```python
class SourceSearchResult(BaseModel):
    """A single search result from a source index."""
    type: str                           # "academic_paper" | "book" | "dataset" | ...
    identifier: str                     # "doi:10.xxx" or "md5:abc123"
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract_snippet: str | None = None
    source_index: str                   # "annas_archive", "libgen", etc.
    source_index_label: str             # "Anna's Archive", "LibGen", etc.
    relevance_score: float | None = None
    full_text_available: bool = False
    file_type: str | None = None        # "pdf", "epub", "djvu", etc.
    download_url: str | None = None     # Direct or proxied download URL
```

### 4.6 Ranking Strategy

Combined score per result:

```
score = sum over source_indexes of:
    relevance_score × source_weight × freshness_decay × availability_bonus

Where:
  source_weight:     Tier S=1.0, A=0.85, B=0.6, C=0.3
  freshness_decay:   1.0 for <2yr, 0.9 for 2-5yr, 0.7 for 5-10yr, 0.5 for >10yr
  availability_bonus: 1.1 if full_text_available, 1.0 otherwise
```

---

## 5. Verify-MCP Shadow Source Integration

### 5.1 Verification Pipeline (Proposed)

```
  Claim
    │
    ▼
┌─────────────────────────────────────────────┐
│ 1. Extract keywords/entities from claim     │  ← LLM (DeepSeek)
│    → ["transformer", "attention", "survey"] │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 2. DOI Lookup via search-mcp                │  ← search_shadow_libraries
│    → [doi:10.1038/..., doi:10.1145/...]     │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 3. Full-text resolution via Sci-Hub/SciDB   │  ← resolve_doi adapter
│    → PDF → extract relevant passage         │     or cached passage
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ 4. Passage-vs-claim comparison              │  ← LLM (DeepSeek)
│    → verdict: supported|refuted|inconclusive│
│    → confidence: 0.0–1.0                    │
│    → evidence_passage: "..."                │
└─────────────────────────────────────────────┘
    │
    ▼
  VerificationResult
```

### 5.2 New Verification Method

```python
"shadow_source_corroboration": {
    "name": "shadow_source_corroboration",
    "description": (
        "Cross-reference the claim against paywalled academic sources "
        "accessible via shadow libraries (Sci-Hub, LibGen, Anna's Archive)."
    ),
    "reliability": 0.88,  # Higher than source_corroboration because
                           # academic papers are more authoritative
}
```

### 5.3 Latency Budget Analysis

| Step | Best Case | Worst Case | Mitigation |
|---|---|---|---|
| 1. Keyword extraction (LLM) | 200ms | 2s | Local DeepSeek, streaming |
| 2. DOI lookup (search-mcp) | 50ms (cached) | 3s (multi-index scrape) | Pre-cache DOIs in PG; bulk DB dumps |
| 3. Full-text resolution (Sci-Hub) | 2s (direct PDF) | 10s (Sci-Hub timeout) | Cache resolved papers in S3/MinIO |
| 4. Passage-vs-claim (LLM) | 500ms | 5s (long paper) | Extract relevant section, not full paper |
| **Total** | **~3s** | **~20s** | Target p95 < 8s |

### 5.4 Pre-Caching Strategy

```
┌──────────────────────────────────────────────────┐
│                Cache Layers                        │
├──────────────────────────────────────────────────┤
│ L1: PG cache (DOI → {title, abstract, authors})   │
│     Schema: shadow_sources_cache table             │
│     TTL: 7 days (metadata), infinite (DOI→paper)  │
│                                                    │
│ L2: File cache (DOI → extracted passage)           │
│     Storage: /data/cache/shadow/{doi_hash}/        │
│     TTL: 30 days                                   │
│                                                    │
│ L3: Full PDF cache (DOI → PDF binary)              │
│     Storage: MinIO/S3 (deduplicated by MD5)        │
│     TTL: 90 days (academic papers don't change)    │
└──────────────────────────────────────────────────┘
```

- **Warm-up:** On startup, load the top 10,000 most-cited DOIs into L1
  from Anna's Archive database dumps.
- **Cache-aside:** On cache miss → resolve → store → return.
- **Eviction:** LRU by last access time. Academic papers older than
  10 years get priority eviction (they're less likely to be cited in
  current claims).

### 5.5 `verify_claim` With Shadow Sources

The existing `verify_claim` endpoint gains a new parameter:

```python
parameters: {
    "claim": "str (required)",
    "methods": "list[str] (optional, default: all)",
    "use_shadow_sources": "bool (optional, default: false)",
}
```

When `use_shadow_sources=true`:
1. `shadow_source_corroboration` is included in methods.
2. The verifier calls search-mcp's `search_shadow_libraries` to find
   relevant academic sources.
3. For each top result (top 3), it resolves the paper and extracts
   the most relevant passage.
4. The LLM compares the claim against the extracted passages.
5. The result includes `evidence_sources` — a list of
   `SourceReference`s with DOI, snippet, and page/paragraph citation.

### 5.6 Safety & Ethics

- **Fail-closed:** If no shadow library is reachable, `shadow_source_corroboration`
  returns `inconclusive`, not `refuted`. Absence of shadow evidence is not evidence.
- **Citation transparency:** All results include full DOI + source index
  attribution. Users know exactly where evidence came from.
- **Configurable:** `SHADOW_SOURCES_ENABLED=false` env var disables all
  shadow library access. Default: `true` (opt-out).
- **No PDF redistribution:** Saimon never serves full PDFs. It extracts
  and caches only the passages relevant to verification.

---

## 6. Content Type Mapping

These shadow-source-derived content types should be registered:

| Content Type | Best Served By | Trigger | Description |
|---|---|---|---|
| `research_note` | Sci-Hub, LibGen, Anna's Archive | User asks for academic paper summary | Structured summary of a specific paper with DOI, key findings, methodology |
| `summary` | Sci-Hub, LibGen, SciDB | User asks "summarize the literature on X" | Aggregate summary of 3–5 papers on a topic, with comparison table |
| `white_paper` | Academic Torrents, Internet Archive | User asks for a survey / review | Deep dive into a research area citing 10+ papers, structured like a lit review |
| `case_study` | Memory of the World, Internet Archive | User asks about a specific historical case or movement | Thematic analysis drawing from curated collections |
| `bibliography` | Anna's Archive, LibGen | User asks "find me papers about X" | Ranked, annotated bibliography with DOIs and source index attribution |

These would be registered via the existing `seed_loader.py` /
self-extend mechanism alongside the 13 existing content types. The
`research_note` and `summary` types already exist in `seed_data.py`;
we add `bibliography` as a new type and extend `white_paper` and
`case_study` to accept shadow-source parameters.

---

## 7. `list_sources` → `list_source_indexes` Fix

### 7.1 Changes to `saimon_mcp/search/server.py`

**New endpoint (primary):**

```python
@app.post("/tools/list_source_indexes")
async def list_source_indexes(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """List available source indexes (Anna's Archive, LibGen, KG, etc.)."""
    ...
```

**Old endpoint (deprecated alias):**

```python
@app.post("/tools/list_sources")
async def list_sources_deprecated(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """[DEPRECATED] Use /tools/list_source_indexes instead."""
    from fastapi.responses import JSONResponse
    resp = await list_source_indexes(payload, request)
    # Add deprecation header
    return JSONResponse(
        content=resp.model_dump(),
        headers={"X-Deprecated": "true",
                 "X-Deprecated-Replacement": "/tools/list_source_indexes"},
    )
```

**Tool manifest update:**

```python
_TOOLS = [
    ...
    {
        "name": "list_source_indexes",
        "description": "List available source indexes (knowledge graph, shadow libraries, web).",
        "parameters": {},
    },
    ...
]
```

### 7.2 Changes to `get_source_detail`

Rename to `get_source_index_detail` with same deprecation pattern.

### 7.3 Response Shape (updated)

```json
{
  "source_indexes": [
    {
      "type": "knowledge_graph",
      "identifier": "kg-root",
      "label": "Knowledge Graph Root",
      "source_count": 1042
    },
    {
      "type": "shadow_library",
      "identifier": "annas_archive",
      "label": "Anna's Archive",
      "source_count": null,
      "tier": "S",
      "status": "available"
    },
    {
      "type": "shadow_library",
      "identifier": "libgen",
      "label": "Library Genesis (LibGen)",
      "source_count": null,
      "tier": "S",
      "status": "available"
    },
    ...
  ]
}
```

---

## 8. SHADOW-SEARCH-1 Slice Spec

### 8.1 Slice Metadata

| Field | Value |
|---|---|
| **Slice** | SHADOW-SEARCH-1 |
| **Branch** | `slice/SHADOW-SEARCH-1` |
| **Parent** | `ai-dev` (current HEAD: all 15 slices merged) |
| **Depends on** | None (standalone addition to search-mcp + verify-mcp) |
| **What** | Shadow library source integration: search tool, verify pipeline, terminology fix |

### 8.2 Scope

| Module | Changes |
|---|---|
| `research_shared/envelope.py` | Add `SourceSearchResult` model |
| `research_shared/shadow_registry.py` | **NEW** — Source index registry with adapter discovery |
| `research_shared/adapters/` | **NEW** — Adapter dir: `base.py`, `annas_archive.py`, `libgen.py`, `scihub.py`, `internet_archive.py`, `academic_torrents.py` |
| `saimon_mcp/search/server.py` | Add `search_shadow_libraries` tool; rename `list_sources`→`list_source_indexes`; add shadow source status to index listing |
| `saimon_mcp/verify/server.py` | Add `shadow_source_corroboration` method; add `use_shadow_sources` param to `verify_claim` |
| `research_shared/seed_data.py` | Add `bibliography` content type; extend `white_paper`, `case_study` shadow params |
| `schema.sql` | Add `shadow_sources_cache` table |

### 8.3 TDD Outline

#### Phase 1: Models & Registry (RED → GREEN)

1. **`test_shadow_models.py`**
   - `test_source_search_result_validation` — valid/invalid DOIs, required fields
   - `test_source_search_result_serialization` — round-trip JSON
   - `test_shadow_registry_list_all` — returns all registered adapters
   - `test_shadow_registry_get_by_name` — lookup by identifier
   - `test_shadow_registry_filter_by_tier` — returns only S-tier, etc.

2. **`research_shared/shadow_registry.py`** (implementation)
   - `ShadowRegistry` class with `register(adapter)`, `list_all()`, `get(name)`, `filter(tier)`

#### Phase 2: Adapters (RED → GREEN)

3. **`test_annas_archive_adapter.py`**
   - `test_search_returns_results` — mock HTTP, verify parsing
   - `test_search_empty_query` — handles edge case
   - `test_resolve_doi_found` — returns result for known DOI
   - `test_resolve_doi_not_found` — returns None gracefully
   - `test_timeout_handling` — adapter timeout → degraded

4. **`test_libgen_adapter.py`** — same pattern

5. **`test_internet_archive_adapter.py`**
   - `test_search_via_open_library_api` — real API integration test
   - `test_rate_limit_backoff` — exponential backoff on 429

6. **`test_academic_torrents_adapter.py`** — same pattern

7. **`test_dedup_engine.py`**
   - `test_deduplicate_by_doi` — same DOI across 3 sources → 1 result
   - `test_deduplicate_by_title_author` — no DOI, title+author match
   - `test_deduplicate_merge_also_available` — `also_available_at` populated
   - `test_deduplicate_no_duplicates` — no false dedup
   - `test_deduplicate_empty_list` — empty input

#### Phase 3: Terminology Fix (RED → GREEN)

8. **`test_list_source_indexes.py`**
   - `test_new_endpoint_returns_source_indexes` — primary endpoint
   - `test_deprecated_endpoint_returns_deprecation_header` — backward compat
   - `test_both_endpoints_return_same_data` — consistency
   - `test_tool_manifest_updated` — `list_source_indexes` in `/tools` response

#### Phase 4: search_shadow_libraries Tool (RED → GREEN)

9. **`test_search_shadow_libraries.py`**
   - `test_search_all_sources` — queries all Tier S adapters
   - `test_search_filtered_sources` — `source_indexes=["libgen"]` only
   - `test_search_deduplicates_cross_index` — dedup engine invoked
   - `test_search_limit_and_offset` — pagination works
   - `test_search_no_results` — empty response, not error
   - `test_search_without_auth` — 401
   - `test_search_degraded_when_adapter_fails` — partial results with degraded status

#### Phase 5: verify-mcp Shadow Integration (RED → GREEN)

10. **`test_shadow_verify.py`**
    - `test_shadow_source_corroboration_method_registered` — in method list
    - `test_verify_claim_with_shadow_sources` — end-to-end mock
    - `test_verify_claim_without_shadow_sources` — default behavior unchanged
    - `test_shadow_sources_disabled_by_env` — `SHADOW_SOURCES_ENABLED=false`

#### Phase 6: Integration (GREEN)

11. **`test_shadow_search_integration.py`** (integration tests)
    - `test_live_annas_archive_search` — real search (gated behind `--run-live` marker)
    - `test_live_libgen_search` — real search
    - `test_end_to_end_verify_with_shadow` — full pipeline: search → resolve → verify

### 8.4 Files to Create/Modify

```
NEW:
  research_shared/shadow_registry.py          # ShadowRegistry
  research_shared/adapters/__init__.py
  research_shared/adapters/base.py            # Abstract base + SourceSearchResult
  research_shared/adapters/annas_archive.py   # Anna's Archive adapter
  research_shared/adapters/libgen.py           # LibGen adapter
  research_shared/adapters/scihub.py           # Sci-Hub/SciDB adapter
  research_shared/adapters/internet_archive.py # Internet Archive adapter
  research_shared/adapters/academic_torrents.py# Academic Torrents adapter
  research_shared/adapters/dedup.py            # Deduplication engine
  tests/shared/test_shadow_models.py
  tests/shared/test_shadow_registry.py
  tests/shared/test_dedup.py
  tests/mcp/test_search/test_search_shadow.py
  tests/mcp/test_search/test_list_source_indexes.py
  tests/mcp/test_verify/test_shadow_verify.py
  tests/mcp/test_integration/test_shadow_search_integration.py

MODIFY:
  research_shared/envelope.py     # Add SourceSearchResult (or put in adapters/base.py)
  saimon_mcp/search/server.py            # +search_shadow_libraries, rename list_sources→list_source_indexes
  saimon_mcp/verify/server.py            # +shadow_source_corroboration, +use_shadow_sources
  research_shared/seed_data.py    # +bibliography content type, extend white_paper/case_study
  schema.sql                      # +shadow_sources_cache table
  AGENTS.md                       # Update Slice Inventory
```

### 8.5 Estimated Test Count

| Layer | Tests | Description |
|---|---|---|
| Models | 5 | SourceSearchResult, ShadowRegistry |
| Adapters | 25 | 5 adapters × ~5 tests each |
| Deduplication | 6 | DOI, title/author, edge cases |
| Terminology fix | 5 | list_source_indexes, tool manifest |
| search_shadow_libraries tool | 8 | search, filter, paginate, auth, degrade |
| verify-mcp shadow | 5 | method, use_shadow_sources, env flag |
| Integration | 8 | Live + mock integration |
| **Total** | **~62** | Plus existing 488 = ~550 |

### 8.6 Validation Gates

```bash
# Pre-PR:
python3 -m pytest tests/ -q
python3 -m compileall research_shared/ saimon_mcp/
ruff check research_shared/ saimon_mcp/
```

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Anna's Archive blocks our IP | Medium | High | Multiple mirrors, rate limiting, bulk DB dumps as primary source |
| Sci-Hub domains seized | High | Medium | SciDB as fallback; Nexus/Library as emerging alternative |
| LibGen HTML structure changes | Medium | Low | Periodic DB dump import; adapter tests detect breakage |
| Legal risk of shadow library access | Low | Medium | `SHADOW_SOURCES_ENABLED=false` opt-out; Saimon never redistributes PDFs |
| Cache staleness (paper retracted) | Low | Low | 7-day metadata TTL; re-verify on cache miss |
| Adapter latency blows p95 budget | Medium | Medium | Timeouts (5s per adapter), parallel queries, degraded mode for slow adapters |

---

## 10. Next Steps

1. **Operator review** this design document.
2. **Decide on bulk DB dump strategy:** Should Saimon maintain its own
   mirror of Anna's Archive / LibGen metadata, or live-scrape?
3. **Start SHADOW-SEARCH-1** after approval:
   ```bash
   git checkout ai-dev && git pull origin ai-dev
   git checkout -b slice/SHADOW-SEARCH-1
   ```
4. **Phase 1 first:** Models + Registry (no scraping yet) — get the
   architecture right before touching shadow libraries.
5. **Phase 2:** Adapters with mock HTTP — test the parsing without
   live scraping.
6. **Phase 3:** Terminology fix — low-risk rename with backward compat.
7. **Phase 4:** Wire `search_shadow_libraries` tool.
8. **Phase 5:** Verify-mcp integration.
9. **Phase 6:** Live integration tests (gated behind `--run-live`).
