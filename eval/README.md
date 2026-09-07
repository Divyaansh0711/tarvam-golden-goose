# Evaluation corpus & test set

## `corpus_spec.py` + `corpus/dictations.jsonl`

512 synthetic dictation records (`raw_asr` + `formatted_text` + `metadata`), the format required
for both this development corpus and Sarvam's separate corpus (see `scripts/import_corpus.py`,
phase 8).

**Ground truth is authored independently of any model.** `corpus_spec.py` deterministically
decides, in plain Python with a fixed random seed, what each record's content is and what the
extraction pipeline should do with it (`expected_decision`, and content checks like
`entity_resolved_as_contains`) — before any LLM is involved. `scripts/generate_corpus.py` then
asks an LLM only to *phrase* each spec as natural dictation text; it never decides what's correct.
This is what keeps the eval from being "a collection of successful examples chosen after the
system was built" (the brief explicitly rules that out) — the expected answers exist whether or
not the system gets them right.

Category breakdown (512 total, chosen to resemble real usage — mostly nothing memory-worthy, plus
enough of each edge case to reveal where the system succeeds, abstains, or fails):

| category | count | what it tests |
|---|---|---|
| `negative_ordinary` | 260 | restraint — ordinary dictation, including incidental name mentions, should produce nothing |
| `entity_clear` | 70 | correct extraction + auto-confirm; 10 pairs test role-update merging across dictations |
| `instruction_clear` | 50 | correct extraction; 3 pairs test exact-restatement dedup, 2 pairs deliberately test a *known limitation* (paraphrased restatement isn't caught by exact-text dedup) |
| `task_clear` | 50 | 25 create+update pairs, each using deliberately varied label phrasing, testing word-overlap task matching across multiple dictations |
| `ambiguous` | 25 | hedged/uncertain statements that should not auto-confirm (pending or none, never a confident commit) |
| `adversarial` | 25 | hypothetical, reported, sarcastic, and third-person-about-someone-else phrasing that must produce nothing, despite superficially resembling a real statement |
| `boundary_scope` | 20 | 8 pairs test that a same-name entity in a different app does NOT merge across the app boundary; 4 test that an explicitly global statement IS retrievable everywhere |
| `recurring_task` | 12 | 8 recurring commitments (no natural end — must be held for confirmation, not auto-committed) + 4 one-off calendar mentions (must NOT be over-flagged as recurring) |

The `recurring_task` category was added after the initial 500-record generation, once
recurring-commitment handling was built (a user question — "does a standing weekly call with Rahul
get remembered, and as what type?" — surfaced that this didn't fit entity, instruction, or one-off
task cleanly, since it has no natural end and the original task type auto-expires after inactivity;
see `app/services/extraction.py`'s `task_recurrence` field). It was generated and appended with
continuing ids via `--append-category`, deliberately without reshuffling or regenerating the
already-committed first 500, so their ids/content stay stable.

Regenerate with `python scripts/generate_corpus.py` (full corpus) or `--pilot N` for a quick
sample. `--seed` controls `corpus_spec.py`'s random seed (default 42, fixed for reproducibility of
*which* scenarios get generated — the LLM's phrasing of them can still vary run to run, which is
why the committed `dictations.jsonl` is the actual corpus used for reported results, not
regenerated on demand). Use `--append-category <name>` to add a new category later, as above,
without disturbing the existing committed records.

## `qa_testset.jsonl`

19 hand-authored grounded Q&A cases, each specifying `setup_dictations` (or `setup_manual` for the
two cases that need a deterministically pending, never-confirmed memory row — one entity, one
recurring task) to seed memory, the `app` the question is asked from, and `expected_grounded` +
`expected_answer_contains`. Written before running the pipeline against them. Covers: direct
answers, rephrased questions, unknown entities, instruction overgeneralization, task recency across
multiple updates (a stale answer citing only the first dictation is wrong), cross-app scope
isolation in both directions (for both entities and instructions), global-scope retrieval,
wrong-premise correction, opinion-refusal, and pending memory correctly never grounding an answer
even though the row exists in the database — including a pending *recurring task* specifically,
added alongside the `recurring_task` corpus category above.

## Running the evaluation

See `scripts/run_eval.py` (phase 7) for how these are actually run and scored.
