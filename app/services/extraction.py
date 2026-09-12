"""Turns one dictation into zero or more memory candidates, and decides
whether each is committed immediately, held for confirmation, or dropped.

This is where the position's central discipline is enforced in code, not
just policy: only literal, explicit statements become candidates at all
(see EXTRACTION_SYSTEM_PROMPT), and even then, only unambiguous ones commit
without a human in the loop (see AUTO_CONFIRM_THRESHOLD in app/config.py).
"""
import sqlite3

from app.config import AUTO_CONFIRM_THRESHOLD, EXTRACTION_MODEL
from app.db import dumps
from app.services import memory_store as store
from app.services.llm import call_tool

EXTRACTION_SYSTEM_PROMPT = """You are Kivi's memory extraction step. You read one transcript of \
something a person dictated and decide whether it contains a LITERAL, EXPLICIT statement \
establishing one of three things Kivi is allowed to remember:

1. entity — the person is stating or clarifying who someone IS (a name, a role, a \
disambiguation), e.g. "that's Rahul from engineering, not the Rahul in finance."
2. instruction — the person is stating a standing rule for their own future behaviour, in plain \
language, e.g. "always CC my manager on client emails."
3. task — the person themselves is actively in the middle of a specific, identifiable piece of \
work, with actual STATE to track — multiple parts, progress that develops, or content that \
accumulates across dictations, e.g. "I'm drafting the PRD for voice search, still need to add the \
metrics section." This requires the person describing their OWN ongoing effort ("I'm drafting/ \
building/working on X, Y is done, Z is left") — not dictating content for something else, \
mentioning an event, or describing someone else's work (see negative examples below). A task can \
be a one-off deliverable (has a natural end state) OR a recurring commitment with no natural end \
(e.g. "I have a weekly call with Rahul every Wednesday") — set `task_recurrence` to "one_off" or \
"recurring" accordingly; for entity/instruction candidates set it to "not_applicable".

Extract ONLY what is literally, explicitly stated. Do not infer, guess, or extrapolate — if the \
transcript is ordinary dictation with no such statement (the common case), return an empty \
candidates list. Do NOT create a candidate from:
- hypothetical or conditional phrasing ("if I were you, I'd always cc...")
- someone else's statement being quoted or reported by the speaker
- emotional state, relationship quality, opinions, or any personal fact not stated as a literal \
identity/instruction/task fact
- a name or app mentioned only in passing, with no clarifying/instructing/task-stating intent
- a single-step reminder or errand with no state to track ("remind me to buy milk", "don't forget \
to call the dentist", "grabbing coffee with Rohan later") — there's nothing to check back on \
later, so this is not task memory; it's an ordinary reminder or social plan outside what Kivi's \
memory is for here
- content or requirements dictated FOR a deliverable ("the chart should show quarterly revenue \
growth", "the paragraph should explain the benefits of remote work") — this is dictating what \
something should contain, not the speaker describing their own ongoing work's state
- a meeting or calendar event mentioned with no statement of work progress ("I'm meeting Sneha for \
lunch") — an event on its own has no state to track
- a report about someone ELSE's work, even if detailed ("Ananya mentioned she's still working on \
the deck") — task memory is for the speaker's own work, not secondhand reports about others
- an observation or bug report with no explicit statement that the speaker is currently working on \
it ("found a bug where the login flow fails") — noting something exists is not the same as \
stating you're actively handling it; only "I'm fixing/working on X" phrasing qualifies
- a piece of work where the person explicitly closes out the WHOLE named effort as entirely done, \
with no sense that it's one part of something ongoing ("finished the backend integration and called \
it done", "wrapped up that whole effort") — task memory exists so Hey Kivi can resume something \
unfinished later, and a fully closed item has nothing left to resume. This is narrow: do NOT apply \
it to a statement that one PART or section of a named, ongoing piece of work is done ("the rough \
draft is now done", "stakeholder review is now also done for the survey summary") — completing one \
part does not mean the larger named work is closed, and these ARE task updates even without \
restating what else remains. When in doubt between "one part done" and "the whole thing closed," \
treat it as a task update, not as closed — false restraint here is worse than a harmless update.
- future intent that hasn't started yet ("I want to outline a blog post about X", "I'm planning to \
draft Y", "I should probably start on Z") — "want to" / "planning to" / "should" describe an \
intention, not work already underway; only present-progressive, already-in-motion phrasing ("I'm \
drafting/outlining/working on X") describes active state to track

`confidence` should be near 1.0 only for unambiguous, self-contained, directly-stated facts. Use \
a lower confidence (below 0.85) for anything that requires resolving an ambiguous pronoun, is \
only partially stated, or could plausibly be read another way — those are queued for a person to \
confirm rather than committed automatically. Do not inflate confidence to force an auto-commit.

`scope_hint` must be "this_app" unless the person explicitly says the fact applies more broadly \
(e.g. "on all my devices", "in general", "everywhere I use Kivi") — "this_app" is always the \
default, never inferred wider.

`quote` must be an exact, verbatim substring of the transcript you were given. `reasoning` is one \
sentence explaining, to a person auditing this later, why this is (or contributes to) a literal \
statement rather than an inference.

Note on recurring commitments: even when confidently and explicitly stated, a recurring task is \
always held for the person to confirm before it's treated as permanent — a wrong guess there \
would persist indefinitely, unlike a one-off task that naturally expires if unused. Set \
confidence normally regardless; that gating happens after your response, not by lowering \
confidence artificially."""

CANDIDATE_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["entity", "instruction", "task"]},
        "quote": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "scope_hint": {"type": "string", "enum": ["this_app", "global"]},
        "task_recurrence": {"type": "string", "enum": ["one_off", "recurring", "not_applicable"]},
        "entity_surface_forms": {"type": ["array", "null"], "items": {"type": "string"}},
        "entity_resolved_as": {"type": ["string", "null"]},
        "entity_role_context": {"type": ["string", "null"]},
        "instruction_rule_text": {"type": ["string", "null"]},
        "task_label": {"type": ["string", "null"]},
        "task_state_summary": {"type": ["string", "null"]},
    },
    "required": [
        "type", "quote", "confidence", "reasoning", "scope_hint", "task_recurrence",
        "entity_surface_forms", "entity_resolved_as", "entity_role_context",
        "instruction_rule_text", "task_label", "task_state_summary",
    ],
}

EXTRACTION_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {"type": "array", "items": CANDIDATE_ITEM_SCHEMA},
    },
    "required": ["candidates"],
}


def extract_candidates(conn: sqlite3.Connection, dictation: dict) -> tuple[list[dict], dict]:
    user_message = (
        f"App: {dictation['app']}\n"
        f"Formatted transcript: {dictation['formatted_text']}\n"
        f"Raw ASR: {dictation['raw_asr']}"
    )
    parsed, stats = call_tool(
        conn=conn,
        purpose="extraction",
        model=EXTRACTION_MODEL,
        system=EXTRACTION_SYSTEM_PROMPT,
        user_message=user_message,
        tool_name="record_candidates",
        tool_description="Record zero or more literal memory candidates found in the transcript.",
        tool_schema=EXTRACTION_TOOL_SCHEMA,
        related_dictation_id=dictation["id"],
        max_tokens=1024,
    )
    return parsed.get("candidates", []), stats


def _scope_for(app: str, scope_hint: str) -> dict:
    return {"global": True} if scope_hint == "global" else {"apps": [app]}


def _apply_entity_candidate(conn: sqlite3.Connection, *, dictation_id: int, app: str, c: dict) -> dict:
    surface_forms = c["entity_surface_forms"] or [c["entity_resolved_as"]]
    existing = store.find_matching_entity(conn, app, surface_forms)
    if existing:
        store.update_entity(
            conn, existing["id"], resolved_as=c["entity_resolved_as"] or existing["resolved_as"],
            role_context=c["entity_role_context"] or existing["role_context"],
            reasoning=f"merged from a later dictation: {c['reasoning']}",
        )
        return {"type": "entity", "decision": "merged", "memory_id": existing["id"], "reasoning": c["reasoning"], "confidence": c["confidence"]}

    status = "confirmed" if c["confidence"] >= AUTO_CONFIRM_THRESHOLD else "pending"
    entity_id = store.create_entity(
        conn, surface_forms=surface_forms, resolved_as=c["entity_resolved_as"] or surface_forms[0],
        role_context=c["entity_role_context"], scope=_scope_for(app, c["scope_hint"]), status=status,
        source_quote=c["quote"], confidence=c["confidence"], source_dictation_id=dictation_id,
        reasoning=c["reasoning"],
    )
    decision = "auto_confirmed" if status == "confirmed" else "pending_confirmation"
    return {"type": "entity", "decision": decision, "memory_id": entity_id, "reasoning": c["reasoning"], "confidence": c["confidence"]}


def _apply_instruction_candidate(conn: sqlite3.Connection, *, dictation_id: int, app: str, c: dict) -> dict:
    rule_text = c["instruction_rule_text"]
    rule_norm = (rule_text or "").strip().lower()
    for instr in store.list_instructions(conn):
        if instr["status"] == "rejected":
            continue
        if not store.instruction_scope_matches(instr["scope"], app, persona=None):
            continue
        if instr["rule_text"].strip().lower() == rule_norm:
            return {"type": "instruction", "decision": "duplicate_ignored", "memory_id": instr["id"], "reasoning": "identical standing instruction already remembered", "confidence": c["confidence"]}

    status = "confirmed" if c["confidence"] >= AUTO_CONFIRM_THRESHOLD else "pending"
    scope = {} if c["scope_hint"] == "global" else {"app": app}
    instruction_id = store.create_instruction(
        conn, rule_text=rule_text, scope=scope, status=status, source_quote=c["quote"],
        confidence=c["confidence"], source_dictation_id=dictation_id, reasoning=c["reasoning"],
    )
    decision = "auto_confirmed" if status == "confirmed" else "pending_confirmation"
    return {"type": "instruction", "decision": decision, "memory_id": instruction_id, "reasoning": c["reasoning"], "confidence": c["confidence"]}


def _apply_task_candidate(conn: sqlite3.Connection, *, dictation_id: int, app: str, c: dict) -> dict:
    label = c["task_label"] or "untitled work"

    if c.get("task_recurrence") == "recurring":
        # A recurring commitment has no natural end, so confirming it wrong
        # would persist indefinitely — held for confirmation regardless of
        # confidence, the same discipline as entities/instructions, and
        # unlike a one-off task (which is low-stakes enough to auto-commit
        # since it just expires if it turns out to be wrong or stale).
        existing = store.find_matching_task(conn, app, label, statuses=("open", "pending"))
        if existing and existing["recurring"]:
            return {
                "type": "task", "decision": "duplicate_ignored", "memory_id": existing["id"],
                "reasoning": "recurring commitment already tracked (confirmed or awaiting confirmation)",
                "confidence": c["confidence"],
            }
        task_id = store.create_task(
            conn, label=label, app=app, last_state_summary=c["task_state_summary"] or "",
            scope=_scope_for(app, c["scope_hint"]), reasoning=c["reasoning"], source_dictation_id=dictation_id,
            status="pending", recurring=True,
        )
        return {"type": "task", "decision": "pending_confirmation", "memory_id": task_id, "reasoning": c["reasoning"], "confidence": c["confidence"]}

    existing = store.find_matching_task(conn, app, label)
    if existing:
        store.append_task_progress(
            conn, task_id=existing["id"], last_state_summary=c["task_state_summary"] or existing["last_state_summary"],
            source_dictation_id=dictation_id, reasoning=c["reasoning"],
        )
        return {"type": "task", "decision": "updated", "memory_id": existing["id"], "reasoning": c["reasoning"], "confidence": c["confidence"]}

    task_id = store.create_task(
        conn, label=label, app=app, last_state_summary=c["task_state_summary"] or "",
        scope=_scope_for(app, c["scope_hint"]), reasoning=c["reasoning"], source_dictation_id=dictation_id,
    )
    return {"type": "task", "decision": "created", "memory_id": task_id, "reasoning": c["reasoning"], "confidence": c["confidence"]}


def ingest_dictation(
    conn: sqlite3.Connection, *, app: str, occurred_at: str, raw_asr: str, formatted_text: str,
    metadata: dict, source: str,
) -> tuple[int, list[dict]]:
    cur = conn.execute(
        """
        INSERT INTO dictations (app, occurred_at, raw_asr, formatted_text, metadata_json, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (app, occurred_at, raw_asr, formatted_text, dumps(metadata), source),
    )
    dictation_id = cur.lastrowid
    dictation = {"id": dictation_id, "app": app, "formatted_text": formatted_text, "raw_asr": raw_asr}

    candidates, stats = extract_candidates(conn, dictation)

    if not candidates:
        store.log_event(
            conn, action="extracted", dictation_id=dictation_id,
            reasoning="no literal, explicit entity/instruction/task statement found — ordinary dictation",
            payload={"model_stats": stats},
        )
        return dictation_id, []

    store.log_event(
        conn, action="extracted", dictation_id=dictation_id,
        reasoning=f"{len(candidates)} candidate(s) found", payload={"candidates": candidates, "model_stats": stats},
    )

    handlers = {"entity": _apply_entity_candidate, "instruction": _apply_instruction_candidate, "task": _apply_task_candidate}
    outcomes = [handlers[c["type"]](conn, dictation_id=dictation_id, app=app, c=c) for c in candidates]
    return dictation_id, outcomes
