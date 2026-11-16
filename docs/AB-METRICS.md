# Release A/B metrics

Four arms, one task set, one report per run. The point is a number per release, measured the
same way every time, so "is this release better" stops being an argument.

| Arm | Context the generator sees | What it isolates |
|---|---|---|
| `baseline` | none; the model answers from its own knowledge | what the model already knew |
| `rag` | top-5 passages from the RAG endpoint, gated abstention **ignored** | retrieval without the quality gate |
| `previous` | top-5 from the previous release's endpoint, abstention respected | the last shipped behaviour |
| `current` | top-5 from the current release's endpoint, abstention respected | this release |

Generation is held constant across arms, including the model and the prompt. Only the context
changes. That is deliberate: swapping the model between arms makes the comparison unreadable,
because harness and model effects cannot be separated after the fact.

## Metrics

| Metric | Definition | Why it is there |
|---|---|---|
| `success_rate` | task answered with every required fact, or refused when the task is unanswerable | the headline |
| `abstain_accuracy` | share of unanswerable tasks actually refused | a release that gains success by inventing answers fails here |
| `groundedness_mean` | share of required facts present in the retrieved context | separates "better model" from "better retrieval" |
| `latency_p50/p95_ms` | retrieval + generation per task | a quality win that doubles latency is a trade, not a win |
| `cost_mean_usd` | estimated input + output tokens at a published rate | same |
| `paired bootstrap` | per-task success difference, 2000 resamples, 95% CI | paired, so one fix and one break do not average into "no change" |

## Goals, pre-registered

`eval_harness/ab_targets.json` holds the thresholds a release must meet. They are relative, not
absolute, so adding tasks does not invalidate them.

- current beats baseline by at least 15 success points
- current is no more than 2 points behind the previous release
- abstain accuracy is 1.0 — one fabricated answer fails the release
- groundedness at least 0.75
- p95 latency no worse than 1.5x the previous release
- mean cost no worse than 1.2x the previous release

A missing arm produces a **skipped** check with its reason, never a pass. An unmeasured goal is
not a met goal.

## Run it

```bash
python scripts/ab_eval.py run \
  --provider live --api-key "$SAIMON_API_KEY" \
  --rag-url http://127.0.0.1:8101 --previous-url http://127.0.0.1:8301 \
  --current-url http://127.0.0.1:8101 \
  --previous-ref <previous git sha> --current-ref <current git sha> \
  --out reports/ab/$(date +%F).json

python scripts/ab_eval.py report --report reports/ab/2026-11-16.json
python scripts/ab_eval.py gate   --report reports/ab/2026-11-16.json   # 1 = fail
```

`--provider fake` runs the whole thing with deterministic answers and no network; that is what
the tests use.

## First measured run, 2026-11-16

Previous release `7a9a8f6`, current `016a965` (the coverage gate), six tasks, `deepseek-v4-pro`:

| Arm | success | abstain | groundedness | p95 ms | cost/task |
|---|---|---|---|---|---|
| baseline | 0.33 | 0.00 | 0.00 | 73 513 | $0.00005 |
| rag | 0.67 | 1.00 | 0.62 | 3 730 | $0.00019 |
| previous | 0.67 | 1.00 | 0.62 | 4 306 | $0.00019 |
| current | 0.67 | 1.00 | 0.62 | 3 859 | $0.00019 |

Two numbers need their caveat stated. Baseline latency is one slow call out of six: with n=6,
p95 is the maximum, so latency and cost need twenty tasks or more before they mean anything.
Baseline groundedness is 0.00 by construction — it sees no context, which is what makes the
retrieval arms' 0.62 readable as a retrieval contribution rather than a model effect.

Gate verdict: **FAIL**, on one check — groundedness 0.625 against a 0.75 minimum. The cause is
visible in the rows: the terse query "In Drake, what is a harness?" retrieves nothing (the gate
abstains), so that task contributes 0 groundedness and the model answers "I do not know". The
other three answerable tasks ground correctly.

That is a real retrieval gap, not a benchmark defect: the same passage is found when the query
carries more words. Until it closes, the gate is advisory and is not wired into CI.
