# RUN.md

**Primary review method: completely local application, SQLite embedded database.**

> Status: scaffolding only (phase 1 of 8). The commands below start the app and confirm the
> database is live; the interactive screens (Dictation feed, Memory, Hey Kivi) land in phases 2-5
> and this file will be updated as each becomes reviewable.

## 1. Runtimes and versions

- Python 3.11+ (developed on 3.13)

## 2. Environment variables

Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — required from phase 3 onward (extraction/generation calls). Not required
  for phase 1.

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

## 7. Primary interactions to try (phase 1)

- Visit `/healthz` — confirms the database exists and lists its tables.
- Visit `/` — landing page (the linked screens are not built yet; see phase tracker in README.md).

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
