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

Hey Kivi's action path (`app/services/hey_kivi.py`) has exactly one LLM call per request: a cheap
intent/slot classifier that decides which of three narrow tools applies (`app/services/tools.py`)
and extracts the relevant phrase. Everything after that — matching the phrase against known
memory, deciding to resolve/apply/resume or decline — is plain, deterministic Python over
already-retrieved rows, not a second model call. That keeps the "must never assume" behavior a
matter of a Python function returning `None`, not a model choosing whether to admit it doesn't
know.

- **Resolve an entity** — "Message Rahul about the launch" resolves the named person, scoped to
  the current app, and cites the dictation that established who they are. An unknown name (e.g.
  "Message Priya" when no such entity exists) is correctly declined, not guessed.
- **Apply a standing instruction** — "Draft a follow-up email to the client" surfaces the
  instruction(s) scoped to that app ("CC manager on client emails").
- **Resume a task** — "Keep working on the PRD for voice search" matches an open task by
  word-overlap (not exact string match — "PRD voice search" and "PRD for voice search" are
  recognized as the same work) and returns its last known state with citations to every dictation
  that contributed to it.
- **Correct non-intervention** — a request with nothing memory-relevant ("what's the weather")
  passes through cleanly; a real recall question ("what's Rahul's role?") is honestly recognized
  as a *different* capability (grounded Q&A) that isn't built yet, rather than being forced into
  one of the three action tools.

A real classification bug was caught and fixed during manual testing: "Message Rahul about X" was
initially routed to `apply_instructions` instead of `resolve_entity`, because both intents are
plausibly present. The fix was a contrastive example in the prompt distinguishing the *blocking*
need (knowing who Rahul is) from an incidental one (composing a message) — see the intent prompt
in `hey_kivi.py`.

**Grounded Q&A** (`app/services/qa.py`) answers free-form questions — "what's Rahul's role?",
"what's the current state of the PRD?" — from confirmed memory scoped to the app, with every
answer citing which entity/instruction/task (and, via `memory_events`, which source dictation(s))
it came from. Two genuinely different "no" cases are both handled correctly: a question with no
matching memory at all ("what's my favorite color?") and a question about someone Kivi has no
entity for ("what's Priya's role?") — both produce an honest refusal, not a guess.

The grounding guardrail is two-layered, not just a prompt instruction: the model must cite which
memory item(s) it used, and a Python post-check independently verifies that a claimed answer with
no citation gets downgraded to a refusal — verified with a mocked test that forces exactly that
failure mode (the model claiming an answer while citing nothing), since it's hard to provoke from
a well-behaved model in normal use but is exactly the case the guardrail exists for.

**Recurring commitments** ("I have a weekly call with Rahul on Wednesday") don't fit any of the
three types cleanly — not an identity statement, not a behavioral rule, and not a one-off task with
a natural end. Forcing one into ordinary task memory would give it the wrong lifecycle: tasks
auto-expire after 14 days of inactivity, which is wrong for a standing commitment with no end at
all. The extractor detects this distinction explicitly (`task_recurrence: "recurring"` vs.
`"one_off"` in `app/services/extraction.py`) and, when recurring, holds the candidate for
confirmation exactly like an entity or instruction would — regardless of confidence — rather than
auto-committing it, since a wrong guess there would otherwise persist indefinitely. Confirming it
clears its expiry permanently. This was added mid-build after testing surfaced the gap; see
`eval/corpus_spec.py`'s `recurring_task` category and `eval/qa_testset.jsonl`'s q019 for how it's
evaluated, including a one-off calendar mention deliberately included to check the extractor
doesn't over-flag ordinary meetings as recurring.

## Evaluation

The corpus (512 records) and Q&A test set (19 hand-authored cases) are documented in
`eval/README.md`, including how their expected outcomes were decided independently of any model
output. The harness that runs them and reports results lands in phase 7.

## Limitations

<!-- TODO(phase 8). -->

## AI use

This README, the code, and the evaluation harness were built with Claude Code, working from the
product position in `docs/POSITIONING.md` / `docs/VISION.md`, which were written independently and
without AI assistance, per the brief's requirement for Part One.

## A note on the LLM provider

The documented, primary provider is **Anthropic** (`ANTHROPIC_API_KEY`, `claude-haiku-4-5` for
extraction, `claude-sonnet-5` for generation) — see `app/services/llm.py`. Mid-build, no Anthropic
key was available, so a temporary alternative was added behind the same interface: **Groq**
(`GROQ_API_KEY`, `openai/gpt-oss-120b`), auto-selected only when no Anthropic key is set. Every
caller (`extraction.py`, and Hey Kivi's tools later) goes through one `call_tool()` function and
never knows which provider answered — swapping back is a one-file change, not a rewrite.

This is disclosed rather than quietly defaulted because it's a real trade-off, not a neutral
choice: Groq's open-weight model has looser guarantees on the "extract only literal, explicit
statements, do nothing for ordinary dictation" discipline the eval is built to measure, and cost
for Groq calls is intentionally left untracked (`$0` in `model_calls`) rather than estimated. If
you're reviewing this and only have one provider's key, either works end-to-end; the numbers in
`eval/results` should be read as produced by whichever provider was configured at run time.

## Build phases (tracking)

- [x] 1. Scaffolding — repo layout, FastAPI skeleton, schema, docs, config
- [x] 2. Core memory store + manual CRUD + Memory screen
- [x] 3. Ingestion + extraction pipeline + Dictation feed screen
- [x] 4. Hey Kivi actions (entity resolution, instructions, task resume)
- [x] 5. Grounded Q&A + refusal handling
- [x] 6. ~500-record corpus + QA testset
- [ ] 7. Evaluation harness + results
- [ ] 8. Corpus import path, reset flow, README/RUN.md finalization
