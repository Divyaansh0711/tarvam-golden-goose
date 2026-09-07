"""Hey Kivi's request pipeline: classify what the person wants, pull only
the memory scoped to their current app/persona, dispatch to the matching
tool, and log the whole decision (retrieved ids, reasoning, latency) so it's
inspectable afterward. This is the "context assembler" from the plan — it
never hands the model a full dump of everything Kivi knows, only what's
scoped to this app/persona and relevant to this one request.

Grounded free-form Q&A ("question" intent) is a fourth, separate path
(app/services/qa.py) — recognizing it as its own intent (rather than
forcing a question into one of the three action tools) matters for the same
reason restraint matters everywhere else in this system: routing it
correctly is what lets qa.py apply its own, stricter grounding guardrail.
"""
import sqlite3
import time

from app.config import EXTRACTION_MODEL
from app.services import memory_store as store
from app.services import qa, tools
from app.services.llm import call_tool

INTENT_SYSTEM_PROMPT = """You are Hey Kivi's intent router. You read one request a person made \
to Kivi and decide which of Kivi's narrow set of capabilities it needs:

1. resolve_entity — the person refers to a specific person, org, or project by name and needs \
Kivi to know who that is in this context (e.g. "email Rahul about the demo", "message Priya").
2. apply_instructions — the person asks Kivi to draft, send, or compose something, where a \
standing instruction might apply (e.g. "draft an email to the client", "write a reply").
3. resume_task — the person wants to continue or reference a specific piece of ongoing work \
(e.g. "keep working on the PRD", "finish the voice search doc").
4. question — the person is asking Kivi to recall or tell them something from memory (e.g. \
"what's Rahul's role", "what was I doing on the PRD"). This is answered from memory directly, not \
by resolving an entity or resuming a task — classify it as question even if it mentions a name or \
a piece of work, whenever the person wants to be TOLD something rather than have Kivi ACT.
5. no_memory_relevant — the request doesn't need any of Kivi's memory (e.g. "what's the weather", \
"summarize this document").

If a request could plausibly need more than one, pick whichever is the BLOCKING need — the thing \
that must be resolved before anything else can happen. For example, "message Rahul about the \
launch" is resolve_entity: knowing who Rahul is blocks everything else, even though sending a \
message is also technically involved. apply_instructions is only for requests centered on \
drafting or sending content itself with no specific named person to resolve first (e.g. "draft an \
email to the client", "write a reply") — not for "message/email/tell <name> ..." requests, which \
are resolve_entity.

`entity_query` is the exact name/phrase referring to a person or project, only if intent is
resolve_entity, otherwise null. `task_query` is the exact phrase describing the work, only if
intent is resume_task, otherwise null. `reasoning` is one sentence explaining the choice, for
someone auditing this decision later."""

INTENT_TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["resolve_entity", "apply_instructions", "resume_task", "question", "no_memory_relevant"],
        },
        "entity_query": {"type": ["string", "null"]},
        "task_query": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["intent", "entity_query", "task_query", "reasoning"],
}


def classify_intent(conn: sqlite3.Connection, *, utterance: str, app: str, persona: str | None) -> tuple[dict, dict]:
    user_message = f"App: {app}\nPersona: {persona or 'none specified'}\nRequest: {utterance}"
    parsed, stats = call_tool(
        conn=conn,
        purpose="hey_kivi_intent",
        model=EXTRACTION_MODEL,
        system=INTENT_SYSTEM_PROMPT,
        user_message=user_message,
        tool_name="route_request",
        tool_description="Decide which Hey Kivi capability this request needs.",
        tool_schema=INTENT_TOOL_SCHEMA,
        max_tokens=512,
    )
    return parsed, stats


def handle_request(conn: sqlite3.Connection, *, utterance: str, app: str, persona: str | None) -> int:
    start = time.monotonic()
    routing, _stats = classify_intent(conn, utterance=utterance, app=app, persona=persona)
    intent = routing.get("intent", "no_memory_relevant")

    entity_ids, instruction_ids, task_ids, dictation_ids = [], [], [], []

    if intent == "resolve_entity":
        outcome = tools.resolve_entity(conn, app=app, query=routing.get("entity_query"))
        entity_ids = outcome.get("entity_ids", [])
        dictation_ids = outcome.get("dictation_ids", [])
    elif intent == "apply_instructions":
        outcome = tools.apply_instructions(conn, app=app, persona=persona)
        instruction_ids = outcome.get("instruction_ids", [])
    elif intent == "resume_task":
        outcome = tools.resume_task(conn, app=app, query=routing.get("task_query"))
        task_ids = outcome.get("task_ids", [])
        dictation_ids = outcome.get("dictation_ids", [])
    elif intent == "question":
        outcome = qa.answer_question(conn, question=utterance, app=app, persona=persona)
        entity_ids = outcome.get("entity_ids", [])
        instruction_ids = outcome.get("instruction_ids", [])
        task_ids = outcome.get("task_ids", [])
        dictation_ids = outcome.get("dictation_ids", [])
    else:
        outcome = {"result": "Nothing in Kivi's memory applies to this request.", "grounded": False, "refused": False}

    latency_ms = int((time.monotonic() - start) * 1000)
    reasoning = outcome.get("reasoning") or routing.get("reasoning", "")

    request_id = store.log_hey_kivi_request(
        conn, kind="action" if intent != "question" else "question", utterance=utterance, app=app,
        persona=persona, intent=intent, retrieved_entity_ids=entity_ids,
        retrieved_instruction_ids=instruction_ids, retrieved_task_ids=task_ids,
        retrieved_dictation_ids=dictation_ids, result_text=outcome["result"],
        grounded=outcome["grounded"], refused=outcome["refused"], reasoning=reasoning,
        latency_ms=latency_ms,
    )
    return request_id
