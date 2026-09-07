# RUN.md

**Primary review method: completely local application, SQLite embedded database.**

> Status: phase 5 of 8. Memory, Dictation feed, and Hey Kivi (three action tools plus grounded
> Q&A) are all reviewable now. Remaining: the ~500-record corpus + eval harness + corpus import
> (phases 6-8).

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
  produce no memory candidate.
- Visit `/hey-kivi` — with `--seed`, try "Message Rahul about the launch timing" (resolves via the
  seeded entity), then a name Kivi doesn't know (e.g. "Message Priya...") to see it correctly
  decline rather than guess. Try "Draft a follow-up email to the client" to see the seeded CC
  instruction applied. For task resume, first create one via the Dictation feed (paste the PRD
  example), then ask Hey Kivi to "keep working on the PRD for voice search" in the same app.
  For grounded Q&A, try "What's Rahul's role?" (answered, cited) and "What's my favorite color?"
  or "What's Priya's role?" (both correctly refused — no memory to support an answer).

## 8. Evaluation

Not yet available (phase 7).

## 9. Corpus import

Not yet available (phase 8).

## 10. Inspecting results / memory state

`db/kivi.db` is a plain SQLite file — inspect with `sqlite3 db/kivi.db` or any SQLite browser.

## 11. Resetting the system

```bash
python scripts/reset.py           # empty database
python scripts/reset.py --seed    # empty database + example seed data
```
