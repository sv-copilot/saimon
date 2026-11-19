
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

## The subject check (2026-11-19)

Two adversarial cases survived the IDF work: `a-twelve` and `a-heroku`. Both are subject
mismatches — the passage contains every word of the question while being about something else.
`a-heroku` returned a Coolify comparison note because it is the corpus's only sentence containing
"Heroku".

A deterministic check: a question's rarest measured content term (df ≤ N, alphabetic, ≥ 4 chars) must
be evidenced by the document itself — in its title, its path, or mentioned M times in the passage.

| N / M | grounding | recall@8 | MRR | abstention | adversarial defended |
|---|---|---|---|---|---|
| off | **0.800** | **0.958** | **0.899** | 0.571 | 0.875 |
| 20 / 2 | 0.709 | 0.833 | 0.802 | 0.786 | 0.938 |
| 10 / 3 | 0.746 | 0.875 | 0.816 | 0.786 | 0.938 |
| 60 / 3 | 0.636 | 0.667 | 0.667 | 0.929 | 0.938 |

Every setting fixes exactly one adversarial case and costs between 5 and 16 points of grounding.
Default is **off**: the check fixes a real failure but is not free, and 0.746 sits just under the
0.75 gate. `SAIMON_RERANK_SUBJECT_MAX_DF=10 SAIMON_RERANK_SUBJECT_MIN_MENTIONS=3` is the profile for
a pipeline where a confident wrong sentence is more expensive than a missing answer.
