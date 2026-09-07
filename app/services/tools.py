"""Hey Kivi's narrow set of memory-backed action tools. Each one is plain,
deterministic Python over already-retrieved memory — no LLM call inside a
tool. The one LLM call in the whole Hey Kivi path is the intent/slot
classifier in hey_kivi.py; once it has decided *what* the person wants and
extracted the relevant phrase, matching that phrase against known memory is
inspectable string/token logic, not another opaque model decision. This
keeps the action path cheap, fast, and easy to audit — and keeps failure
modes ("I don't know who that is") a matter of Python returning None, not a
model deciding whether to admit it doesn't know.

Grounded free-form Q&A (phase 5) is a different path — that one does need
generation, because synthesizing an answer from multiple memories isn't a
lookup. These tools only ever return a name, an instruction list, or a task
summary that was already sitting in the database.
"""
import sqlite3

from app.services import memory_store as store


def resolve_entity(conn: sqlite3.Connection, *, app: str, query: str | None) -> dict:
    if not query:
        return {"result": "No specific person or project was named in the request.", "grounded": False, "refused": True, "entity_ids": []}

    entity = store.find_matching_entity(conn, app, [query])
    if not entity:
        return {
            "result": f"I don't know who \"{query}\" is in {app} yet — nothing to go on, so I won't guess.",
            "grounded": False, "refused": True, "entity_ids": [],
        }

    store.touch_entity_used(conn, entity["id"])
    role = f" ({entity['role_context']})" if entity.get("role_context") else ""
    return {
        "result": f"\"{query}\" resolves to {entity['resolved_as']}{role}.",
        "grounded": True, "refused": False, "entity_ids": [entity["id"]],
        "dictation_ids": [entity["source_dictation_id"]] if entity.get("source_dictation_id") else [],
    }


def apply_instructions(conn: sqlite3.Connection, *, app: str, persona: str | None) -> dict:
    matching = [
        i for i in store.list_instructions(conn, status="confirmed")
        if i["active"] and store.instruction_scope_matches(i["scope"], app, persona)
    ]
    if not matching:
        return {"result": f"No standing instructions apply to {app}.", "grounded": False, "refused": True, "instruction_ids": []}

    for i in matching:
        store.touch_instruction_used(conn, i["id"])
    lines = "; ".join(i["rule_text"] for i in matching)
    return {
        "result": f"Applying standing instruction(s): {lines}",
        "grounded": True, "refused": False, "instruction_ids": [i["id"] for i in matching],
    }


def resume_task(conn: sqlite3.Connection, *, app: str, query: str | None) -> dict:
    if not query:
        return {"result": "No specific piece of work was named in the request.", "grounded": False, "refused": True, "task_ids": []}

    task = store.find_matching_task(conn, app, query)
    if not task:
        return {
            "result": f"No open work matching \"{query}\" in {app}.",
            "grounded": False, "refused": True, "task_ids": [],
        }
    return {
        "result": f"Resuming \"{task['label']}\": {task['last_state_summary']}",
        "grounded": True, "refused": False, "task_ids": [task["id"]],
        "dictation_ids": task["source_dictation_ids"],
    }
