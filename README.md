# Kivi — Semantic Memory for Hey Kivi

Sarvam "Golden Goose" submission. Part One (product position) lives in [`docs/POSITIONING.md`](docs/POSITIONING.md)
and [`docs/VISION.md`](docs/VISION.md) — written independently, before any of this code existed.
This README covers Part Two: the system built from that position.

> Status: work in progress, built in phases. This section will be filled in as each phase lands;
> see the phase list below for what's done.

## Product

<!-- TODO(phase 8): summarize what the product does, in plain terms, for a normal user. -->

## Why three memory types, and not more

Semantic memory here means exactly three things, each traceable to something the user explicitly
said: **entities** (who someone is, in context), **standing instructions** (a rule stated in plain
language), and **task/working memory** (the live state of a specific piece of ongoing work).
Nothing is inferred from dictation content in the background — see `docs/POSITIONING.md` and
`docs/VISION.md` for why, and `services/extraction.py` for how that's enforced in code, not just
policy.

**A deliberate scope decision**: the brief's own example ("find the dictation I did around 5pm
yesterday in Slack") implies general content search across all past dictation. Our position rules
that out explicitly — it's the Recall-style life-log pattern it names as the failure mode to avoid.
Instead, "recovering information distributed across multiple dictations" is handled by task memory
accreting state across dictations about the *same, explicitly identified* piece of work — bounded
and explicit, not a general search index.

## Architecture

<!-- TODO(phase 8): diagram + component walkthrough. -->

## Use cases implemented

<!-- TODO: filled in as phases 3-5 land. -->

## Evaluation

<!-- TODO(phase 7): how to read eval/results, what the numbers mean. -->

## Limitations

<!-- TODO(phase 8). -->

## AI use

This README, the code, and the evaluation harness were built with Claude Code, working from the
product position in `docs/POSITIONING.md` / `docs/VISION.md`, which were written independently and
without AI assistance, per the brief's requirement for Part One.

## Build phases (tracking)

- [x] 1. Scaffolding — repo layout, FastAPI skeleton, schema, docs, config
- [x] 2. Core memory store + manual CRUD + Memory screen
- [ ] 3. Ingestion + extraction pipeline + Dictation feed screen
- [ ] 4. Hey Kivi actions (entity resolution, instructions, task resume)
- [ ] 5. Grounded Q&A + refusal handling
- [ ] 6. ~500-record corpus + QA testset
- [ ] 7. Evaluation harness + results
- [ ] 8. Corpus import path, reset flow, README/RUN.md finalization
