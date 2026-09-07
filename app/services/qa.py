"""Grounded free-form Q&A. Unlike the action tools in tools.py, answering a
question genuinely requires synthesis — "what's Rahul's role" isn't a
lookup key, it's a question about content in a specific memory item. So
this is the one place in Hey Kivi that generates prose, and the one place
that most needs a hard guardrail against inventing an answer.

The guardrail is two-layered, not just a prompt request:
1. The model is given ONLY the confirmed memory scoped to this app/persona,
   each tagged with an id, and told to cite the ids it used.
2. A Python post-check (not the model's word for it) enforces that a claimed
   answer without any citation is downgraded to a refusal. "Grounded" in
   the hey_kivi_requests log means "cited something that was actually
   retrieved," not "the model said it was confident."
"""
import sqlite3

from app.config import GENERATION_MODEL
from app.services import memory_store as store
from app.services.llm import call_tool

QA_SYSTEM_PROMPT = """You are Hey Kivi's memory Q&A step. You are given the confirmed memory \
Kivi holds for one app (entities, standing instructions, and tasks — each tagged with an id), and \
one question the person asked. Answer using ONLY the content of those items. Cite the id of every \
item your answer depends on.

If none of the provided items answer the question, set answered to false and say so plainly — do \
not use outside knowledge, do not guess, and do not answer a related-but-different question \
instead. An honest "I don't have anything on that" is always correct when the memory doesn't \
contain the answer; a confident-sounding guess is always wrong, even if it happens to be right."""

QA_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answered": {"type": "boolean"},
        "answer_text": {"type": "string"},
        "cited_entity_ids": {"type": "array", "items": {"type": "integer"}},
        "cited_instruction_ids": {"type": "array", "items": {"type": "integer"}},
        "cited_task_ids": {"type": "array", "items": {"type": "integer"}},
        "reasoning": {"type": "string"},
    },
    "required": ["answered", "answer_text", "cited_entity_ids", "cited_instruction_ids", "cited_task_ids", "reasoning"],
}


def _format_context(entities: list[dict], instructions: list[dict], tasks: list[dict]) -> str:
    lines = []
    for e in entities:
        role = f" — {e['role_context']}" if e.get("role_context") else ""
        lines.append(f"[entity#{e['id']}] {e['resolved_as']}{role} (also known as: {', '.join(e['surface_forms'])})")
    for i in instructions:
        lines.append(f"[instruction#{i['id']}] {i['rule_text']}")
    for t in tasks:
        lines.append(f"[task#{t['id']}] \"{t['label']}\" (status: {t['status']}) — {t['last_state_summary']}")
    return "\n".join(lines) if lines else "(nothing remembered for this app yet)"


def answer_question(conn: sqlite3.Connection, *, question: str, app: str, persona: str | None) -> dict:
    entities = [e for e in store.list_entities(conn, "confirmed") if store.entity_scope_matches(e["scope"], app)]
    instructions = [
        i for i in store.list_instructions(conn, "confirmed")
        if i["active"] and store.instruction_scope_matches(i["scope"], app, persona)
    ]
    tasks = [t for t in store.list_tasks(conn) if t["app"] == app]

    context = _format_context(entities, instructions, tasks)
    user_message = f"App: {app}\nMemory Kivi holds for this app:\n{context}\n\nQuestion: {question}"

    parsed, stats = call_tool(
        conn=conn,
        purpose="hey_kivi_qa",
        model=GENERATION_MODEL,
        system=QA_SYSTEM_PROMPT,
        user_message=user_message,
        tool_name="answer_question",
        tool_description="Answer the question using only the provided memory, citing what was used.",
        tool_schema=QA_TOOL_SCHEMA,
        max_tokens=1024,
    )

    entity_ids = parsed.get("cited_entity_ids", [])
    instruction_ids = parsed.get("cited_instruction_ids", [])
    task_ids = parsed.get("cited_task_ids", [])
    has_citation = bool(entity_ids or instruction_ids or task_ids)

    if parsed.get("answered") and not has_citation:
        # Model claimed an answer but cited nothing it was given — don't take
        # its word for "grounded". Downgrade to a refusal instead.
        return {
            "result": "I can't point to anything specific that supports an answer, so I won't guess.",
            "grounded": False, "refused": True, "entity_ids": [], "instruction_ids": [], "task_ids": [],
            "dictation_ids": [], "reasoning": "answer was claimed without citing any retrieved memory — overridden to a refusal",
        }

    if not parsed.get("answered"):
        return {
            "result": parsed.get("answer_text") or "I don't have anything on that.",
            "grounded": False, "refused": True, "entity_ids": [], "instruction_ids": [], "task_ids": [],
            "dictation_ids": [], "reasoning": parsed.get("reasoning", ""),
        }

    for eid in entity_ids:
        store.touch_entity_used(conn, eid)
    for iid in instruction_ids:
        store.touch_instruction_used(conn, iid)

    dictation_ids = []
    for eid in entity_ids:
        dictation_ids += store.get_source_dictation_ids(conn, "entities", eid)
    for iid in instruction_ids:
        dictation_ids += store.get_source_dictation_ids(conn, "instructions", iid)
    for tid in task_ids:
        dictation_ids += store.get_source_dictation_ids(conn, "tasks", tid)

    return {
        "result": parsed["answer_text"], "grounded": True, "refused": False,
        "entity_ids": entity_ids, "instruction_ids": instruction_ids, "task_ids": task_ids,
        "dictation_ids": sorted(set(dictation_ids)), "reasoning": parsed.get("reasoning", ""),
    }
