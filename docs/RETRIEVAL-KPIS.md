
## Experiments (2026-11-19)

Four configurations, same image, same database, run side by side on temporary ports so nothing
depended on a deploy:

| configuration | grounding | recall@8 | MRR | abstention | adversarial defended |
|---|---|---|---|---|---|
| previous defaults | 0.782 | 0.917 | 0.858 | 0.571 | 0.938 |
| cap 3 chunks/doc | 0.746 | 0.917 | 0.858 | 0.571 | 0.938 |
| cap 3 + title 0.08 | 0.764 | 0.958 | 0.899 | 0.571 | 0.875 |
| **title 0.08, no cap** | **0.800** | **0.958** | **0.899** | 0.571 | 0.875 |
| title 0.08, coverage 0.40 | 0.746 | 0.833 | 0.802 | 0.786 | 0.875 |
| title 0.08, coverage 0.55 | 0.618 | 0.792 | 0.760 | 0.929 | 0.938 |

Two conclusions, both against intuition:

- **Diversity hurts.** Capping one document's chunks costs 3.6 points of grounding. A document's
  neighbouring chunks carry the rest of the argument; replacing them with a different document's
  opening paragraph spreads the context and loses the fact. Default is now off.
- **The title weight earns its keep.** +1.8 grounding, +4 recall, +4 MRR, at the cost of one
  adversarial case (2 of 16 fooled instead of 1).

Coverage is the safety dial, not a free parameter: 0.25 → 0.55 raises abstention from 0.571 to 0.929
and cuts grounding from 0.800 to 0.618. For client-facing use where a confident wrong answer is
expensive, `SAIMON_RERANK_MIN_COVERAGE=0.55` is the profile to run; for an operator who will read the
sources, 0.25 answers more questions.
