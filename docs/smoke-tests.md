# Saimon Smoke Tests

End-to-end test cases that exercise every tool across all 6 MCPs.
Run these after any deployment to verify the full platform.

## Prerequisites

```bash
# Staging
export BASE="http://127.0.0.1"
export KEY_SEARCH="sk-test-search-key"
export KEY_GENERATE="sk-test-generate-key"
export KEY_EXPORT="sk-test-export-key"
export KEY_EVALUATE="sk-test-evaluate-key"
export KEY_VERIFY="sk-test-verify-key"
export KEY_EXPLORE="sk-test-explore-key"
export TID="00000000-0000-0000-0000-000000000000"
```

## Smoke Test Suite

### 1. Health Check — All 6 MCPs

```bash
for port in 8101 8102 8103 8104 8105 8106; do
  curl -s $BASE:$port/health
done
```

**Expected:** All return `{"status":"ok"}` with `database: connected` or `llm: connected`.

---

### 2. Search — Shadow Libraries (`saimon_search_scholarly`)

```bash
curl -s -X POST $BASE:8101/tools/search_shadow_libraries \
  -H "X-Saimon-API-Key: $KEY_SEARCH" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}01\",\"content_type\":\"search\",\"parameters\":{\"query\":\"deep learning optimization\",\"limit\":5}}"
```

**Expected:** `status: success`, `total_results > 0`, results from multiple `source_index` values.

**Follow-up — Filter by source:**
```bash
# Same but with source_indexes=["libgen"]
```

**Expected:** All results have `source_index: "libgen"`.

---

### 3. Search — Knowledge Graph (`saimon_search_knowledge_graph`)

```bash
curl -s -X POST $BASE:8101/tools/search_knowledge_graph \
  -H "X-Saimon-API-Key: $KEY_SEARCH" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}02\",\"content_type\":\"search\",\"parameters\":{\"query\":\"verification\"}}"
```

**Expected:** `status: success` or `degraded`. Returns previously stored verification nodes if DB has data.

---

### 4. List Sources (`saimon_list_sources`)

```bash
curl -s -X POST $BASE:8101/tools/list_source_indexes \
  -H "X-Saimon-API-Key: $KEY_SEARCH" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}03\",\"content_type\":\"search\"}"
```

**Expected:** `source_indexes` array contains knowledge_graph + 5 shadow_library entries (annas_archive, libgen, scihub, internet_archive, academic_torrents). Each shadow library has `tier` and `status`.

---

### 5. Verify — True Claim (`saimon_verify_claim`)

```bash
curl -s -X POST $BASE:8105/tools/verify_claim \
  -H "X-Saimon-API-Key: $KEY_VERIFY" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}04\",\"content_type\":\"verify\",\"parameters\":{\"claim\":\"The Earth orbits the Sun\",\"use_shadow_sources\":true}}"
```

**Expected:** `overall_verdict: "supported"`, 5 verification methods, `evidence_source` field present.

---

### 6. Verify — False Claim

```bash
curl -s -X POST $BASE:8105/tools/verify_claim \
  -H "X-Saimon-API-Key: $KEY_VERIFY" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}05\",\"content_type\":\"verify\",\"parameters\":{\"claim\":\"The moon is made of green cheese\",\"use_shadow_sources\":true}}"
```

**Expected:** `overall_verdict: "refuted"`, high confidence scores.

---

### 7. Verify — Ambiguous Claim

```bash
curl -s -X POST $BASE:8105/tools/verify_claim \
  -H "X-Saimon-API-Key: $KEY_VERIFY" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}06\",\"content_type\":\"verify\",\"parameters\":{\"claim\":\"AGI will be achieved by 2030\"}}"
```

**Expected:** `overall_verdict: "inconclusive"` or `"supported"`. Should not crash.

---

### 8. List Verification Methods

```bash
curl -s -X POST $BASE:8105/tools/list_verification_methods \
  -H "X-Saimon-API-Key: $KEY_VERIFY" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}07\",\"content_type\":\"verify\"}"
```

**Expected:** 5 methods: source_corroboration, logical_consistency, authority_check, temporal_validity, shadow_source_corroboration. Each has `reliability` score.

---

### 9. Generate Content (`saimon_generate_content`)

```bash
curl -s -X POST $BASE:8102/tools/generate_content \
  -H "X-Saimon-API-Key: $KEY_GENERATE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}08\",\"content_type\":\"summary\",\"parameters\":{\"prompt\":\"Summarize the Transformer architecture in 3 sentences\"}}"
```

**Expected:** `status: success`, `data.content` contains generated text. Tests LLM connectivity.

**Follow-up — Different content type:**
```bash
# content_type: "research_note", tone: "technical"
```

**Expected:** Content generated with different style.

---

### 10. List Content Types

```bash
curl -s -X POST $BASE:8102/tools/list_content_types \
  -H "X-Saimon-API-Key: $KEY_GENERATE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}09\",\"content_type\":\"generate\"}"
```

**Expected:** 14 content types: blog_post, summary, research_note, social_post, email_draft, press_release, case_study, white_paper, job_posting, meeting_notes, proposal, tutorial, product_review, bibliography.

---

### 11. Evaluate Content (`saimon_evaluate_content`)

```bash
curl -s -X POST $BASE:8104/tools/evaluate_content \
  -H "X-Saimon-API-Key: $KEY_EVALUATE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}10\",\"content_type\":\"evaluate\",\"parameters\":{\"content\":\"The Transformer architecture introduced self-attention mechanisms that process all tokens in parallel, replacing recurrent neural networks for sequence modeling tasks.\",\"criteria\":\"accuracy,clarity\"}}"
```

**Expected:** `status: success`, returns scored evaluation with per-criterion breakdown. Tests LLM connectivity for evaluate-mcp.

---

### 12. Explore Content

```bash
curl -s -X POST $BASE:8106/tools/explore_content \
  -H "X-Saimon-API-Key: $KEY_EXPLORE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}11\",\"content_type\":\"explore\",\"parameters\":{\"query\":\"transformer\"}}"
```

**Expected:** `status: success` or `degraded`. Returns items from knowledge graph matching the query.

---

### 13. Browse by Type

```bash
curl -s -X POST $BASE:8106/tools/browse_by_type \
  -H "X-Saimon-API-Key: $KEY_EXPLORE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}12\",\"content_type\":\"explore\",\"parameters\":{\"content_type\":\"research_note\"}}"
```

**Expected:** `status: success` or `degraded`. Returns items filtered by content_type.

---

### 14. Export Content

```bash
curl -s -X POST $BASE:8103/tools/export_content \
  -H "X-Saimon-API-Key: $KEY_EXPORT" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}13\",\"content_type\":\"export\",\"parameters\":{\"content\":\"# Test\\n\\nThis is a test document.\",\"format\":\"markdown\"}}"
```

**Expected:** `status: success`. Returns formatted content.

---

### 15. End-to-End Pipeline

```bash
# 1. Search for sources
SEARCH=$(curl -s -X POST $BASE:8101/tools/search_shadow_libraries \
  -H "X-Saimon-API-Key: $KEY_SEARCH" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}14\",\"content_type\":\"search\",\"parameters\":{\"query\":\"attention mechanisms neural networks\",\"limit\":3}}")
echo "Search: $(echo $SEARCH | grep -o '\"status\":\"[^\"]*\"')"

# 2. Verify a claim from the topic
VERIFY=$(curl -s -X POST $BASE:8105/tools/verify_claim \
  -H "X-Saimon-API-Key: $KEY_VERIFY" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}15\",\"content_type\":\"verify\",\"parameters\":{\"claim\":\"Attention mechanisms improved machine translation quality\",\"use_shadow_sources\":true}}")
echo "Verify: $(echo $VERIFY | grep -o '\"overall_verdict\":\"[^\"]*\"')"

# 3. Generate research note
GEN=$(curl -s -X POST $BASE:8102/tools/generate_content \
  -H "X-Saimon-API-Key: $KEY_GENERATE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}16\",\"content_type\":\"research_note\",\"parameters\":{\"prompt\":\"Explain attention mechanisms in 2 sentences\",\"tone\":\"technical\"}}")
echo "Generate: $(echo $GEN | grep -o '\"status\":\"[^\"]*\"')"

# 4. Evaluate the generated content
CONTENT=$(echo $GEN | python3 -c "import sys,json; print(json.load(sys.stdin)['data'].get('content',''))" 2>/dev/null)
EVAL=$(curl -s -X POST $BASE:8104/tools/evaluate_content \
  -H "X-Saimon-API-Key: $KEY_EVALUATE" \
  -H "Content-Type: application/json" \
  -d "{\"trace_id\":\"${TID}17\",\"content_type\":\"evaluate\",\"parameters\":{\"content\":\"$CONTENT\",\"criteria\":\"accuracy,clarity\"}}")
echo "Evaluate: $(echo $EVAL | grep -o '\"status\":\"[^\"]*\"')"

# 5. Check DB for persisted data
echo "DB after pipeline:"
docker exec saimon-postgres psql -U saimon -d saimon -t -c \
  "SELECT 'audit:' || count(*) FROM audit_log; SELECT 'kg:' || count(*) FROM knowledge_graph_nodes; SELECT 'cache:' || count(*) FROM shadow_sources_cache;"
```

**Expected:** All steps return `success`. Database shows increased counts.

---

### 16. Auth — All 6 MCPs reject missing key

```bash
for port in 8101 8102 8103 8104 8105 8106; do
  code=$(curl -s -o /dev/null -w "%{http_code}" $BASE:$port/tools)
  echo "Port $port: $code (expect 401)"
done
```

**Expected:** All return 401.

---

### 17. Auth — All 6 MCPs accept correct key

```bash
for svc in search:8101:sk-test-search-key generate:8102:sk-test-generate-key export:8103:sk-test-export-key evaluate:8104:sk-test-evaluate-key verify:8105:sk-test-verify-key explore:8106:sk-test-explore-key; do
  name="${svc%%:*}"; rest="${svc#*:}"; port="${rest%%:*}"; key="${rest#*:}"
  code=$(curl -s -o /dev/null -w "%{http_code}" $BASE:$port/tools -H "X-Saimon-API-Key: $key")
  echo "  $name-mcp: $code (expect 200)"
done
```

**Expected:** All return 200.

---

## Quick Run (One-Liner)

```bash
ssh staging-rs 'bash -s' < docs/smoke-tests.sh
```

Or from local:
```bash
cd /Users/simon/saimon
python3 -m pytest tests/ -q          # 616 unit tests
# Then run smoke tests on staging manually or via script
```

## Pass Criteria

| # | Test | What It Validates |
|---|---|---|
| 1 | Health | All 6 services alive |
| 2-3 | Search | shadow + KG search working |
| 4 | List Sources | Source registry correct |
| 5-7 | Verify | True/false/ambiguous claims |
| 8 | Methods | Verification method registry |
| 9-10 | Generate | LLM content + content types |
| 11 | Evaluate | LLM scoring |
| 12-13 | Explore | KG discovery |
| 14 | Export | Output formatting |
| 15 | Pipeline | End-to-end: search→verify→generate→evaluate |
| 16-17 | Auth | Fail-closed security |
