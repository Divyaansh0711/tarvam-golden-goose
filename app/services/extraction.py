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
3. task — the person is stating the current state of a specific, identifiable piece of ongoing \
work, e.g. "I'm drafting the PRD for voice search, still need to add the metrics section."

Extract ONLY what is literally, explicitly stated. Do not infer, guess, or extrapolate — if the \
transcript is ordinary dictation with no such statement (the common case), return an empty \
candidates list. Do NOT create a candidate from:
- hypothetical or conditional phrasing ("if I were you, I'd always cc...")
- someone else's statement being quoted or reported by the speaker
- emotional state, relationship quality, opinions, or any personal fact not stated as a literal \
identity/instruction/task fact
- a name or app mentioned only in passing, with no clarifying/instructing/task-stating intent

`confidence` should be near 1.0 only for unambiguous, self-contained, directly-stated facts. Use \
a lower confidence (below 0.85) for anything that requires resolving an ambiguous pronoun, is \
only partially stated, or could plausibly be read another way — those are queued for a person to \
confirm rather than committed automatically. Do not inflate confidence to force an auto-commit.

`scope_hint` must be "this_app" unless the person explicitly says the fact applies more broadly \
(e.g. "on all my devices", "in general", "everywhere I use Kivi") — "this_app" is always the \
default, never inferred wider.

`quote` must be an exact, verbatim substring of the transcript you were given. `reasoning` is one \
sentence explaining, to a person auditing this later, why this is (or contributes to) a literal \
statement rather than an inference."""

CANDIDATE_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ["entity", "instruction", "task"]},
        "quote": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "scope_hint": {"type": "string", "enum": ["this_app", "global"]},
        "entity_surface_forms": {"type": ["array", "null"], "items": {"type": "string"}},
        "entity_resolved_as": {"type": ["string", "null"]},
        "entity_role_context": {"type": ["string", "null"]},
        "instruction_rule_text": {"type": ["string", "null"]},
        "task_label": {"type": ["string", "null"]},
        "task_state_summary": {"type": ["string", "null"]},
    },
    "required": [
        "type", "quote", "confidence", "reasoning", "scope_hint",
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
