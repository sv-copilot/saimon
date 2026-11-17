# Local document ingest

Two tools, one job each.

`scripts/ingest_sources.py` walks a fixed source manifest, chunks each file and writes
through the product's own `store_content` tool. Right for one document, or for verifying the
API path works; it costs a request, an audit line and a model call per chunk.

`scripts/bulk_ingest.py` writes the same rows straight to Postgres in batches of 500, then
fills embeddings in a second pass. Right for thousands of documents.

```bash
# write everything (idempotent, resumable)
docker run --rm --user 1000:1000 --network saimon_default --env-file ~/.ingest.env2 \
  --entrypoint python -v ~/saimon:/app:ro -v ~/drake-governance/.docs:/src/governance:ro \
  ... ghcr.io/sv-copilot/saimon:main /app/scripts/bulk_ingest.py --write

# fill embeddings, highest-value collections first
docker run -d --name saimon-embed --user 1000:1000 --network saimon_default \
  --env-file ~/.ingest.env2 -e OMP_NUM_THREADS=6 --entrypoint python \
  -v ~/saimon:/app:ro ghcr.io/sv-copilot/saimon:main \
  /app/scripts/bulk_ingest.py --embed --batch 24
```

## What it writes

One node per chunk, `content_type = 'source_document'`, `collection` from the source, and
metadata carrying `path`, `doc_type`, `chunk_index`, `doc_chunks`, `mtime` and `sha256`.

The sha256 is the idempotency key: a chunk already in the graph is skipped, so a re-run after
an edit stores only what changed. Interrupting the run costs nothing.

`source_document` is registered on first write, because `knowledge_graph_nodes.content_type`
is a foreign key into `content_type_registry`.

## Source manifest

| Source | Root | Collection |
|---|---|---|
| governance | `drake-governance/.docs` | governance |
| drake | `drake-public` | drake_public |
| drake_pmo | `drake-pmo` | drake_pmo |
| site | `spencervaradi-site/src/content` | site_content |
| writing | `writing` | writing |
| needle | `work/needle` | novel_canon |
| kdp | `work/hand-recovery` | kdp |
| saimon_self | `saimon` | saimon_self |
| vault | `vaults/workspace` | vault |

## Two things learned the hard way

- The image's default entrypoint is the MCP dispatcher. A script needs
  `--entrypoint python`, or it answers `Unknown MCP: python`.
- The image runs as uid 999; personal files are 600 on uid 1000. Without
  `--user 1000:1000` the walk dies on the first private note.

## Embedding throughput

The ONNX model is CPU-bound and fastembed does not parallelise across processes: three
containers competing produced 0.66 embeds/s in total, while one process with
`OMP_NUM_THREADS=6` produced 4.8/s. Run one, not three.
