# RUN.md

**Primary review method: completely local application, SQLite embedded database.**

> Status: phase 8 of 8, in progress. The full product (Memory, Dictation feed, Hey Kivi with
> grounded Q&A), the 512-record eval corpus + 19-case Q&A test set, the evaluation harness, and the
> corpus-import path are all built and documented below. The harness has been verified correct
> (it caught and helped fix two real bugs — see README) but the full 512-record replay has not yet
> been run to completion end-to-end in one pass; see README's Evaluation section for current status.

## 1. Runtimes and versions

- Python 3.11+ (developed on 3.13)

## 2. Environment variables

Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — the documented provider for submission. Required from phase 3 onward
  (extraction/generation calls); not required for phases 1-2.
- `GROQ_API_KEY` — a temporary dev-time alternative to `ANTHROPIC_API_KEY`, added mid-build while
  no Anthropic key was available (see `app/services/llm.py`). If both are unset or only Groq is
  set, the app auto-selects Groq; set `KIVI_LLM_PROVIDER=anthropic` explicitly to force Anthropic
  once a key exists. **This submission's primary review path uses Anthropic** — see README for
  why Groq isn't the recommended long-term provider (weaker guarantees on the "extract only
  literal statements" discipline the eval depends on).

## 3. Install dependencies

```bash
cd kivi-golden-goose
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Create and migrate the database

```bash
python scripts/migrate.py
python scripts/seed.py   # optional: adds 2 example dictations + 1 entity + 1 instruction
```

## 5. Start the process

```bash
uvicorn app.main:app --reload
```

## 6. Interface to open

http://127.0.0.1:8000

## 7. Primary interactions to try (phase 3)

- Visit `/healthz` — confirms the database exists and lists its tables.
- Visit `/memory` — with `--seed`, you'll see a confirmed entity (Rahul) and instruction (CC
  manager on client emails). Try: editing an entity, adding a new instruction manually, marking a
  task done, deleting something and confirming it's gone.
- Visit `/dictations` — try the example transcripts (including the brief's own "Aditya/Kivi
  service" example). Try pasting ordinary dictation with nothing memory-worthy in it, and a
  hypothetical/reported statement ("if I were you, I'd always CC...") — both should correctly
  produce no memory candidate. Try `I have a weekly mid-week call with Rahul on Wednesday` (app
  `calendar`) — this should land in the Memory screen's pending inbox awaiting confirmation as a
  recurring commitment, not auto-commit as an ordinary (expiring) task.
- Visit `/hey-kivi` — with `--seed`, try "Message Rahul about the launch timing" (resolves via the
  seeded entity), then a name Kivi doesn't know (e.g. "Message Priya...") to see it correctly
  decline rather than guess. Try "Draft a follow-up email to the client" to see the seeded CC
  instruction applied. For task resume, first create one via the Dictation feed (paste the PRD
  example), then ask Hey Kivi to "keep working on the PRD for voice search" in the same app.
  For grounded Q&A, try "What's Rahul's role?" (answered, cited) and "What's my favorite color?"
  or "What's Priya's role?" (both correctly refused — no memory to support an answer).

## 8. Evaluation

```bash
python scripts/run_eval.py                # full run: 512-record corpus + 19-case Q&A set
python scripts/run_eval.py --qa-only       # just the Q&A set (fast, ~19 isolated LLM calls)
python scripts/run_eval.py --corpus-only   # just the corpus replay
python scripts/run_eval.py --limit 40      # quick partial corpus run
```

This calls the real product code end-to-end (no mocking) against a fresh, isolated database — it
never touches `db/kivi.db`, so running it has no effect on the live app. Results are written to
`eval/results/latest/` (overwritten on each run — see item 10). A run over the full corpus makes
roughly 500-550 LLM calls; on a rate-limited provider this can take a while and may need retries
(the harness retries each call once automatically and records a `harness_error` case rather than
crashing if a call still fails).

## 9. Corpus import

To import a separate corpus (e.g. Sarvam's internal 500-dictation corpus) into the **live**
application database, so it can be explored interactively via `/memory` and `/hey-kivi`:

```bash
python scripts/import_corpus.py path/to/corpus.jsonl
python scripts/import_corpus.py path/to/corpus.jsonl --limit 50   # quick partial import
```

Expected format: JSONL, one record per line —
`{"raw_asr": "...", "formatted_text": "...", "app": "slack", "occurred_at": "2026-01-05T09:00:00", "metadata": {}}`.
Only `raw_asr` and `formatted_text` are required; `app` defaults to `"imported"` if the source
corpus has no per-record application context (our memory model scopes by app, so records without
one land in a single shared scope rather than being guessed at), `occurred_at` defaults to import
time, `metadata` defaults to `{}`. `scripts/import_corpus.py` includes a validation pass that fails
fast with the offending line number if any record is missing a required field.

After importing: start the app (item 5) and visit `/memory` to see what was learned (confirmed
items, and anything held in the pending-confirmation inbox), then `/hey-kivi` to ask questions or
issue requests grounded in the imported history. A plain, per-record processing log — the input,
what was extracted or correctly left alone, the reasoning, and latency for every record — is
written to `eval/results/latest_import/import_log.jsonl` (this is descriptive, not scored: there's
no predetermined "expected" outcome for a real corpus, unlike the eval harness in item 8).

## 10. Inspecting results / memory state

- `db/kivi.db` — the live application database (plain SQLite; inspect with `sqlite3 db/kivi.db` or
  any SQLite browser). This is what `/memory`, `/dictations`, and `/hey-kivi` read from, and what
  `scripts/import_corpus.py` writes into.
- `eval/results/latest/` — output of `scripts/run_eval.py` (item 8): `summary.md` (human-readable
  report), `summary.json` (machine-readable), `corpus_cases.jsonl` / `qa_cases.jsonl` (full detail
  per case: input, expected vs. actual, reasoning, citations, latency), `corpus.db` (the replayed
  corpus database), `qa_dbs/<id>.db` (each Q&A case's isolated database).
- `eval/results/latest_import/import_log.jsonl` — output of `scripts/import_corpus.py` (item 9).

## 11. Resetting the system

```bash
python scripts/reset.py           # empty database
python scripts/reset.py --seed    # empty database + example seed data
```
