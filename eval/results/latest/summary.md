# Evaluation results

Generated: 2026-09-09 19:19:58

## Corpus replay

- **512 records**, **493 infra errors** (rate-limited, not scored)
- Pass rate **excluding** infra errors (the real quality signal): **100.0%**
- Pass rate including infra errors as failures (pessimistic floor): **3.7%**

### Outcome breakdown

| bucket | count |
|---|---|
| harness_error | 493 |
| correct_non_intervention | 11 |
| correct_intervention | 8 |

### By category

| category | correct_intervention | correct_non_intervention | harness_error |
|---|---|---|---|
| negative_ordinary | 0 | 11 | 249 |
| entity_clear | 4 | 0 | 66 |
| instruction_clear | 2 | 0 | 48 |
| boundary_scope | 1 | 0 | 19 |
| adversarial | 0 | 0 | 25 |
| task_clear | 1 | 0 | 49 |
| ambiguous | 0 | 0 | 25 |
| recurring_task | 0 | 0 | 12 |

### Latency (extraction, ms)
mean 2747.3, median 2124.0, p95 2457, max 75686

### Database growth (after full replay)

| table | rows |
|---|---|
| dictations | 22 |
| entities | 5 |
| instructions | 2 |
| tasks | 1 |
| memory_events | 27 |
| model_calls | 19 |

### Model usage

| purpose | calls | input tok | output tok | cost (USD) | avg latency (ms) |
|---|---|---|---|---|---|
| extraction | 19 | 23304 | 3781 | 0.000000 | 9041 |

## Grounded Q&A

- **19 cases**, 17 infra errors (rate-limited, not scored)
- Pass rate excluding infra errors: **100.0%**
- Should-answer cases correct: 0/0
- Should-refuse cases correct: 2/2
- **17 case(s) errored (infra failure, not scored)**: q001, q002, q003, q004, q005, q006, q007, q008, q010, q011, q012, q013, q014, q015, q016, q017, q019 — re-run to get a real verdict for these
- Latency (ms): mean 639.5, median 639.5
- Total cost: $0.000000 across 893 tokens

## Notes

- `false_positive` and `ambiguous_over_confident` are the buckets that matter most for trust — they represent Kivi assuming something it wasn't told. `cross_app_leak` represents a scope-isolation failure. `known_limitation` is an expected, documented outcome (paraphrased instruction restatement isn't caught by exact-text dedup), not scored as a defect.
- Per-case detail, including the exact input, extraction reasoning, and citations, is in `corpus_cases.jsonl` and `qa_cases.jsonl` in this directory. The replayed corpus database (`corpus.db`) and each QA case's isolated database (`qa_dbs/<id>.db`) are included for direct inspection with `sqlite3` or any SQLite browser.