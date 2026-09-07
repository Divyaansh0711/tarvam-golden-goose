# Kivi — Semantic Memory for Hey Kivi

Sarvam "Golden Goose" submission. Part One (product position) lives in [`docs/POSITIONING.md`](docs/POSITIONING.md)
and [`docs/VISION.md`](docs/VISION.md) — written independently, before any of this code existed.
This README covers Part Two: the system built from that position.

## Product

Kivi already listens to how you dictate and gets your words right — names, spellings, tone. This
adds the layer above that: Kivi remembers who the people in your work are, the standing rules
you've told it to follow, and the specific pieces of work you're in the middle of — so that when
you ask Hey Kivi to act, it doesn't need to be re-briefed every time.

Concretely, three things:
- **Who someone is** — say "that's Rahul from engineering, not the Rahul in finance" once, and Hey
  Kivi resolves "message Rahul" correctly from then on, in that same context.
- **A standing rule** — say "always CC my manager on client emails" once, and Hey Kivi applies it
  whenever it drafts a client email, without being told again.
- **What you're in the middle of** — mention progress on a piece of work across a few dictations,
  and Hey Kivi can pick it back up ("keep working on the PRD") with the full, current state.

Everything Kivi remembers is visible on one screen (Memory), traces back to something you actually
said (never something inferred from listening in), and is one click from being corrected or
forgotten — the same trust model as fixing a mispronunciation. And it's honest about the edges: it
declines to guess about someone it doesn't know, refuses to answer a question its memory doesn't
support, and — for the one case with no natural end (a standing weekly commitment) — asks you to
confirm before treating it as permanent.

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

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    SQLite (db/kivi.db)                │
                    │  dictations · entities · instructions · tasks         │
                    │  memory_events (audit trail) · model_calls · hey_kivi_requests │
                    └───────────────▲───────────────────────────▲──────────┘
                                    │                            │
   Dictation feed ──▶ extraction.py │                    tools.py / qa.py ◀── Hey Kivi
   (paste a transcript)  │          │                            │      (act or ask)
                          │  1 LLM call: extract literal          │  1 LLM call: classify intent
                          │  entity/instruction/task candidates,  │  (+ slot), then plain Python
                          │  auto-confirm or queue for review     │  matches against retrieved,
                          │                                       │  already-scoped memory —
                          ▼                                       ▼  no second model call per tool
                    memory_store.py (single read/write path;      qa.py: 1 LLM call to synthesize
                    every mutation logged to memory_events)       an answer ONLY from retrieved
                                    │                              memory, cited — Python
                                    ▼                              post-check downgrades any
                          Memory screen (view/edit/                uncited claim to a refusal
                          confirm/dismiss/forget)
```

- **`app/services/llm.py`** — the only place that talks to a model. `call_tool()` forces a single
  structured tool call (never free-text parsing) and logs every call's tokens/latency/cost to
  `model_calls`. Dispatches between Anthropic and Groq behind one interface (see below) — no other
  file knows or cares which one answered.
- **`app/services/extraction.py`** — turns one dictation into zero or more typed candidates,
  decides auto-confirm vs. hold-for-confirmation vs. reject, and handles entity merging / task
  accretion across multiple dictations. This is where the position's "explicit origin only"
  discipline is enforced in code.
- **`app/services/memory_store.py`** — the single read/write path for entities, instructions, and
  tasks. Every mutation — from extraction, from Hey Kivi, or from a person editing the Memory
  screen by hand — logs to `memory_events`, which is what makes "why did Kivi do that" answerable
  from the database alone, and what lets a merged/updated entity cite every dictation that shaped
  it (not just the one it was first created from).
- **`app/services/hey_kivi.py` / `tools.py` / `qa.py`** — the context assembler and the four things
  Hey Kivi can do: resolve an entity, apply an instruction, resume a task, or answer a question.
  Each action tool is one LLM call (intent + slot extraction) followed by deterministic Python
  matching against already-retrieved, already-scoped memory — never a second model call inside a
  tool. Q&A is the one path that genuinely needs generation (synthesizing an answer from multiple
  memories isn't a lookup), so it carries its own two-layered grounding guardrail instead.
- **`app/routers/*` + `app/templates/*`** — a server-rendered FastAPI + Jinja2 UI (no separate
  frontend build/toolchain), three screens: Dictation feed, Memory, Hey Kivi.
- **`eval/` + `scripts/run_eval.py` + `scripts/import_corpus.py`** — the corpus, the Q&A test set,
  the harness that scores the real pipeline against both, and the path for importing an external
  corpus into the live app for interactive review. See `eval/README.md` and RUN.md.

Everything is plain SQLite with hand-written migrations (`db/migrations/`) — no ORM, no vector
store. Retrieval is a scoped SQL query (by app, by status), not embedding search: the position
explicitly rules out building a general-purpose search index over personal content, and at this
scale (a handful of entities/instructions/tasks per app) a full scoped scan is simpler, cheaper,
and more inspectable than approximate retrieval would be.

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
  as a *different* capability (grounded Q&A, see below) rather than being forced into one of the
  three action tools.

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

**A single-step reminder is not a task.** Importing a small real-world-shaped sample surfaced
another gap immediately: "remind me to buy milk" was classified as a one-off task, technically
satisfying the letter of "a specific, identifiable piece of ongoing work" while missing the spirit
of it — there's no state to track, nothing to check back on. Fixed by tightening the task
definition in `extraction.py`'s prompt to require actual trackable state (multiple parts, progress
that develops), with an explicit negative example; verified the reminder now correctly produces
nothing while the real PRD-drafting example is unaffected.

## Evaluation

The corpus (512 records) and Q&A test set (19 hand-authored cases) are documented in
`eval/README.md`, including how their expected outcomes were decided independently of any model
output.

`scripts/run_eval.py` replays the corpus through the real pipeline into a fresh, isolated database
(never the live `db/kivi.db`) and runs the Q&A set against independently-seeded memory, scoring
every case into a bucket — `correct_intervention` / `correct_non_intervention` (the two "it worked"
buckets), `false_positive` / `false_negative` / `wrong_decision` (real failures), `cross_app_leak`
(a scope-isolation failure — checked explicitly for the 8 `boundary_scope` pairs), and
`known_limitation` (an expected, documented outcome — the paraphrased-instruction-restatement case
from `eval/README.md` — not scored as a defect). Results land in `eval/results/latest/`: a
human-readable `summary.md`, machine-readable `summary.json`, full per-case detail in
`corpus_cases.jsonl` / `qa_cases.jsonl`, and the actual replayed SQLite databases for direct
inspection. See RUN.md item 8 for exact commands.

**Current status**: the harness itself is built and has already proven its worth — running the
19-case Q&A set against it caught a real bug (task-state updates were overwriting rather than
merging progress across dictations, see above) before the full corpus run ever completed. The full
512-record replay has not yet finished end-to-end in one pass: the temporary Groq provider's
free-tier daily token limit (200,000/day) was exhausted by cumulative usage across corpus
generation and this session's live testing, partway through the run. The harness retries each call
once and records a `harness_error` case rather than crashing when a call still fails, so a
rate-limited run degrades gracefully rather than silently corrupting results — but a *complete,
uninterrupted* run (and the results committed to this repo) should be produced on the Anthropic
provider, which doesn't share this constraint, before this submission is treated as final. If you
are reviewing this and `eval/results/latest/` looks incomplete or absent, that is why — re-run
`python scripts/run_eval.py` with a working `ANTHROPIC_API_KEY` to produce the full report.

## Limitations

- **Full corpus evaluation incomplete** — see Evaluation above. The harness is verified correct;
  the full 512-record run needs to complete on the Anthropic provider before this is final.
- **Instruction dedup is exact-text only.** A restatement of an existing rule in different words
  (not a near-verbatim repeat) is treated as a new, separate instruction rather than recognized as
  a duplicate. Deliberately included as a known case in the eval corpus (`instruction_clear`'s
  paraphrase pairs) rather than papered over.
- **Task and entity matching are simple heuristics, not semantic understanding.** Task labels match
  by word-overlap (Jaccard over non-stopword tokens); entities match by exact (case-insensitive)
  surface-form overlap. This is a deliberate simplicity choice — genuinely picking apart "Bob" vs.
  "Robert" as the same person, for instance, would need real entity resolution, and would trade the
  system's inspectability (a human can read the matching code) for a capability the position's
  three use cases don't actually require.
- **The 0.85 auto-confirm confidence threshold is a fixed heuristic**, not yet tuned against
  measured outcomes — the full eval run (once complete) is what real threshold calibration would
  be based on, rather than an number chosen up front.
- **Groq (the temporary dev-time provider) has looser structured-output guarantees than Anthropic**
  and a low free-tier daily rate limit (see Evaluation above and "A note on the LLM provider"
  below) — not the documented provider for submission for exactly these reasons.
- **No general search over dictation content**, by deliberate design (see "A deliberate scope
  decision" above) — task memory recovers state across dictations about the *same, explicitly
  identified* work; it does not let Hey Kivi search everything ever said.
- **Single-user, no authentication** — appropriate for a local demo; the position doesn't address
  multi-tenant concerns and neither does this build.
- **The eval corpus is synthetic** (LLM-phrased over deterministically-authored specs), not real
  user data. `scripts/import_corpus.py` (see RUN.md) is how the system is meant to be checked
  against a real corpus — Sarvam's own separate 500-dictation corpus, per the brief.

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
- [x] 6. 512-record corpus + 19-case QA testset
- [x] 7. Evaluation harness (built + verified; full corpus run pending, see Evaluation above)
- [x] 8. Corpus import path, reset flow, README/RUN.md finalization
