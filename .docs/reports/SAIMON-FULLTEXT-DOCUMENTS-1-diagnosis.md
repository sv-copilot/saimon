# SAIMON-FULLTEXT-DOCUMENTS-1 (#216) — Diagnosis

**Status:** resolved (documentation + regression guard)
**Date:** 2026-09-10
**Repo:** saimon

## Root cause

The empty `documents` table is **not** a fulltext-store problem. `documents`
is the **api-mcp's per-user document table** (SAIMON-DOCUMENTS-1), created at
runtime by `saimon_mcp/api/server.py::_ensure_documents_table` for the
Research/Cockpit UI's user-uploaded documents. It is empty because no user has
uploaded a document through the api-mcp — not because fulltext ingestion is
broken.

Fulltext is stored in the **live knowledge graph**, not `documents`:

| Store | Table | Populated? |
|---|---|---|
| Fulltext documents + chunks | `knowledge_graph_nodes` (`fulltext_document`, `fulltext_chunk`) | ✅ 161 rows |
| Shadow source metadata | `shadow_sources_cache` | ✅ 3 rows |
| Verified facts | `observations` | ✅ 511 rows |
| **Per-user documents** (api-mcp) | `documents` | ✅ expected 0 rows |

## Evidence trail (fulltext path)

1. `POST /tools/download_fulltext` → `_download_fulltext_flow`
   (`saimon_mcp/search/server.py`).
2. Adapter `fetch_fulltext` downloads bytes → `extract_text` → `chunk_text`.
3. `store_shadow_fulltext` uploads bytes to S3 and upserts
   `shadow_sources_cache` (`research_shared/s3_storage.py`).
4. `persist_fulltext_document` writes a `fulltext_document` node + N
   `fulltext_chunk` nodes into `knowledge_graph_nodes` with `part_of` edges
   (`research_shared/fulltext.py`).
5. Retrieval (`search_knowledge_graph` → `_vector_search` / `_keyword_search`)
   queries `knowledge_graph_nodes` — the same live store.

## Conclusion

- `documents` is **not** the canonical fulltext store and is **not** legacy
  dead code — it serves a distinct api-mcp feature.
- Fulltext ingestion and retrieval already point at the live store
  (`knowledge_graph_nodes`); there is no broken ingestion and no fulltext
  reader that queries `documents`.

## Changes

- `research_shared/fulltext.py`: added `FULLTEXT_STORE_TABLE` constant and made
  `persist_fulltext_document` reference it explicitly.
- `schema.sql`: documented that `knowledge_graph_nodes` is the fulltext store
  and that `documents` is intentionally absent from the canonical schema.
- `saimon_mcp/api/server.py`: clarified `_ensure_documents_table` is the
  per-user document store, unrelated to fulltext.
- `tests/shared/test_fulltext_store.py`: regression guard locking in the
  invariant (fulltext → `knowledge_graph_nodes`, never `documents`).
