# Evaluation results

Generated: 2026-09-12 13:19:50

## Corpus replay

- **512 records**, **0 infra errors** (rate-limited, not scored)
- Pass rate **excluding** infra errors (the real quality signal): **91.0%**
- Pass rate including infra errors as failures (pessimistic floor): **91.0%**

### Outcome breakdown

| bucket | count |
|---|---|
| correct_non_intervention | 287 |
| correct_intervention | 153 |
| wrong_decision | 36 |
| ambiguous_handled_correctly | 24 |
| false_negative | 7 |
| known_limitation | 2 |
| false_positive | 2 |
| ambiguous_over_confident | 1 |

### By category

| category | ambiguous_handled_correctly | ambiguous_over_confident | correct_intervention | correct_non_intervention | false_negative | false_positive | known_limitation | wrong_decision |
|---|---|---|---|---|---|---|---|---|
| negative_ordinary | 0 | 0 | 0 | 258 | 0 | 2 | 0 | 0 |
| entity_clear | 0 | 0 | 50 | 0 | 0 | 0 | 0 | 20 |
| instruction_clear | 0 | 0 | 43 | 0 | 0 | 0 | 2 | 5 |
| boundary_scope | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 5 |
| adversarial | 0 | 0 | 0 | 25 | 0 | 0 | 0 | 0 |
| task_clear | 0 | 0 | 38 | 0 | 7 | 0 | 0 | 5 |
| ambiguous | 24 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| recurring_task | 0 | 0 | 7 | 4 | 0 | 0 | 0 | 1 |

### Latency (extraction, ms)
mean 2990.9, median 2096.5, p95 6356, max 7506

### Database growth (after full replay)

| table | rows |
|---|---|
| dictations | 512 |
| entities | 57 |
| instructions | 42 |
| tasks | 32 |
| memory_events | 700 |
| model_calls | 512 |

### Model usage

| purpose | calls | input tok | output tok | cost (USD) | avg latency (ms) |
|---|---|---|---|---|---|
| extraction | 512 | 1177140 | 48215 | 1.418215 | 2989 |

## Grounded Q&A

- **19 cases**, 0 infra errors (rate-limited, not scored)
- Pass rate excluding infra errors: **100.0%**
- Should-answer cases correct: 10/10
- Should-refuse cases correct: 9/9
- Latency (ms): mean 4230.6, median 4027
- Total cost: $0.171091 across 82291 tokens

## Notes

- `false_positive` and `ambiguous_over_confident` are the buckets that matter most for trust — they represent Kivi assuming something it wasn't told. `cross_app_leak` represents a scope-isolation failure. `known_limitation` is an expected, documented outcome (paraphrased instruction restatement isn't caught by exact-text dedup), not scored as a defect.
- Per-case detail, including the exact input, extraction reasoning, and citations, is in `corpus_cases.jsonl` and `qa_cases.jsonl` in this directory. The replayed corpus database (`corpus.db`) and each QA case's isolated database (`qa_dbs/<id>.db`) are included for direct inspection with `sqlite3` or any SQLite browser.