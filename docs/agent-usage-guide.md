# Saimon Agent Usage Guide

How AI agents (VS Code Copilot, Cline, Cursor, OpenClaw) should use Saimon
MCP tools for research, verification, and content generation.

## Available Tools

### Search

| Tool | Best For | Example Query |
|---|---|---|
| `saimon_search_archives` | Finding papers in the public archives (Internet Archive, OpenAlex, Crossref, arXiv) | `"transformer attention mechanisms survey"` |
| `saimon_search_knowledge_graph` | Finding previously stored research in the KG | `"AI monetization report"` |
| `saimon_list_sources` | Checking which source indexes are available | (no arguments needed) |

### Verification

| Tool | Best For | Example |
|---|---|---|
| `saimon_verify_claim` | Fact-checking any claim with 5 methods + DeepSeek | `"Python was created by Guido van Rossum in 1991"` |
| `saimon_list_verification_methods` | Understanding what verification methods exist | (no arguments needed) |

### Content Generation

| Tool | Best For | Example |
|---|---|---|
| `saimon_generate_content` | Generating research notes, summaries, white papers | `content_type="research_note"`, `prompt="RAG architecture patterns"` |
| `saimon_list_content_types` | Finding which content types are available | (no arguments needed) |

### Quality & Discovery

| Tool | Best For | Example |
|---|---|---|
| `saimon_evaluate_content` | Scoring generated content against quality criteria | `content="...your text..."`, `criteria="accuracy,completeness"` |
| `saimon_explore_content` | Finding related content in the knowledge graph | `query="neural networks"` |
| `saimon_browse_by_type` | Browsing KG entries by content type | `type_name="research_note"` |
| `saimon_export_content` | Formatting output as markdown, json, or html | `content="...your text..."`, `format="markdown"` |

## Research Workflows

### Basic: Verify a Claim

```
User: "Was the Transformer architecture introduced in 2017?"

1. saimon_verify_claim(claim="The Transformer architecture was introduced in 2017")
   → Returns: SUPPORTED, 0.95 confidence, cites "Attention Is All You Need (Vaswani et al., 2017)"

Response: "Yes. The Transformer architecture was introduced in the 2017 paper
'Attention Is All You Need' by Vaswani et al. Verification confidence: 0.95."
```

### Intermediate: Research a Topic

```
User: "Research the latest advances in graph neural networks"

1. saimon_search_scholarly(query="graph neural networks advances 2024", limit=5)
   → Returns 5 papers with DOIs, authors, abstracts

2. For each key claim found in papers:
   saimon_verify_claim(claim="GNNs outperform CNNs on molecular property prediction")

3. saimon_generate_content(
     content_type="research_note",
     prompt="Summarize advances in graph neural networks based on [sources]",
     tone="technical"
   )

4. saimon_evaluate_content(content="[generated note]", criteria="accuracy,completeness")

5. saimon_export_content(content="[evaluated note]", format="markdown")
```

### Advanced: Full Research Pipeline

```
User: "Write a white paper on AI monetization opportunities"

1. saimon_search_archives(query="AI market size projections 2030", limit=10)
2. saimon_search_archives(query="API monetization models AI agents", limit=10)

3. For each major claim from search results:
   saimon_verify_claim(claim="...", use_archive_sources=true)

4. saimon_explore_content(query="AI monetization")
   → Check if we already have research on this topic

5. saimon_generate_content(
     content_type="white_paper",
     prompt="AI monetization opportunities for MCP tools in 2026...",
     tone="technical",
     depth="comprehensive"
   )

6. saimon_evaluate_content(content="[white paper]", criteria="accuracy,completeness,clarity,sourcing")

7. saimon_export_content(content="[evaluated paper]", format="markdown")
```

## Response Guidelines for Agents

1. **Always cite sources.** Use DOI, title, and source index from search results.
2. **Show confidence.** Include the verification confidence score when reporting facts.
3. **Flag uncertainty.** If a claim is `inconclusive` or `refuted`, say so explicitly.
4. **Use the right content type.** 14 types available — `research_note` for findings,
   `white_paper` for deep dives, `summary` for overviews, `bibliography` for sources.
5. **Evaluate before delivering.** Run `saimon_evaluate_content` on generated output
   before showing it to the user.
6. **Store findings.** Generated content and verifications are automatically persisted
   to the knowledge graph for future retrieval.

## Tool Selection Flowchart

```
User asks a question
  │
  ├─ Is it a factual claim?
  │   → saimon_verify_claim
  │
  ├─ Needs literature search?
  │   → saimon_search_scholarly
  │
  ├─ Needs stored knowledge?
  │   → saimon_search_knowledge_graph + saimon_explore_content
  │
  ├─ Needs content creation?
  │   → saimon_generate_content → saimon_evaluate_content → saimon_export_content
  │
  └─ Needs source inventory?
      → saimon_list_sources + saimon_list_content_types
```

## Error Handling

- If a tool returns `"status":"error"`, read the `errors` field for details
- If `"status":"degraded"`, partial results are available — use what you have
- If one archive is unreachable, other adapters may still return results
- LLM-dependent tools (verify, generate) fall back to heuristics when LLM is down
- Database-dependent tools gracefully degrade when DB is unreachable
