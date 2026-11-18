# Retrieval KPIs

`scripts/measure_retrieval.py` answers three questions that used to be one number.

| KPI | Question | Deterministic |
|---|---|---|
| **recall@k** | did the document that answers the question come back at all? | yes |
| **grounding@k** | do the retrieved passages contain the required facts? | yes |
| **abstention** | on questions the corpus cannot answer, how often is nothing returned? | yes |

Why they are separate: a ranker can put the right document first and still miss the sentence with the
fact; grounding can look healthy because a wrong document repeats the words; and both can be perfect
on answerable questions while the system confidently answers unanswerable ones. One number hid all
three failure modes.

## Current results

69 tasks: 55 answerable across ten collections, 14 unanswerable near-misses. k = 8.

| metric | value |
|---|---|
| grounding@8 | **0.782** |
| recall@8 (24 gold-labelled tasks) | **0.917** |
| MRR | 0.858 |
| abstention (14 tasks) | **0.571** |
| latency p50 / p95 | 418 ms / 578 ms |

Grounding is above the release gate (0.75) for the first time. Recall and MRR only exist for tasks
that name a gold document — the 24 seeded from cooking, outdoors, data, delivery and finance.

## Why not use answer success

The A/B's success metric needs a model, and the model is noisy: the model-alone baseline moved from
0.154 to 0.231 between two identical runs on the same 39 tasks. That is an eight-point floor, which
is larger than every retrieval change measured this week. The KPIs above run no completions, so a
two-point move is a two-point move; a 69-task sweep takes about four minutes.

## Known gap: confident answers to unanswerable questions

Six of fourteen unanswerable questions still return something: `u-redis`, `u-audio-royalty`,
`u-editor`, `u-enterprise`, `u-saffron`, `u-latitude`.

Two fixes were tried and withdrawn, both measured:

| version | grounding | abstention |
|---|---|---|
| no subject gate | **0.782** | 0.571 |
| hard gate (refuse if top passage lacks the named subject) | 0.745 | 0.714 |
| filter (rank among passages that mention it) | 0.764 | 0.571 |

The subject gate cannot work with pool-relative statistics: "Saimon" appears in most candidates and
"Redis" in none, and both look the same to a frequency test over 32 rows. The fix is corpus-level IDF
for anchor terms — count the term against `knowledge_graph_nodes`, not against the candidate pool.

## Running it

```bash
SAIMON_SEARCH_KEY=... python scripts/measure_retrieval.py --k 8 \
  --json-out reports/retrieval-2026-11-18.json
```

Tasks live in `fixtures/ab/tasks-v3.json`. Answerable tasks carry `must_include`; the ones from the
seeded fields also carry `gold`, the document that answers them, which is what makes recall
measurable.
