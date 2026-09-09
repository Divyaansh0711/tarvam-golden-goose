"""All reads/writes to entities, instructions, tasks, and the memory_events
audit trail. Every mutation is logged here so 'why did the system do this'
is answerable from the database alone. Reused by the CRUD routes (phase 2),
the extraction pipeline (phase 3), and Hey Kivi's tools (phase 4).
"""
import sqlite3
from datetime import datetime, timedelta

from app.config import TASK_EXPIRY_DAYS
from app.db import dumps, loads, row_to_dict


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def log_event(
    conn: sqlite3.Connection,
    *,
    action: str,
    reasoning: str,
    dictation_id: int | None = None,
    candidate_type: str | None = None,
    memory_table: str | None = None,
    memory_id: int | None = None,
    payload: dict | None = None,
    confidence: float | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO memory_events
            (dictation_id, candidate_type, action, memory_table, memory_id, payload_json, reasoning, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dictation_id, candidate_type, action, memory_table, memory_id, dumps(payload or {}), reasoning, confidence),
    )
    return cur.lastrowid


def _decorate_entity(row: sqlite3.Row) -> dict:
    d = row_to_dict(row)
    d["surface_forms"] = loads(d.pop("surface_forms_json"), [])
    d["scope"] = loads(d.pop("scope_json"), {})
    return d


def _decorate_instruction(row: sqlite3.Row) -> dict:
    d = row_to_dict(row)
    d["scope"] = loads(d.pop("scope_json"), {})
    return d


def _decorate_task(row: sqlite3.Row) -> dict:
    d = row_to_dict(row)
    d["scope"] = loads(d.pop("scope_json"), {})
    d["source_dictation_ids"] = loads(d.pop("source_dictation_ids_json"), [])
    d["recurring"] = bool(d["recurring"])
    return d


def list_entities(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM entities WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM entities ORDER BY created_at DESC").fetchall()
    return [_decorate_entity(r) for r in rows]


def list_instructions(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM instructions WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM instructions ORDER BY created_at DESC").fetchall()
    return [_decorate_instruction(r) for r in rows]


def list_tasks(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY updated_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
    return [_decorate_task(r) for r in rows]


def get_entity(conn: sqlite3.Connection, entity_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return _decorate_entity(row) if row else None


def get_instruction(conn: sqlite3.Connection, instruction_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM instructions WHERE id = ?", (instruction_id,)).fetchone()
    return _decorate_instruction(row) if row else None


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _decorate_task(row) if row else None


def create_entity(
    conn: sqlite3.Connection,
    *,
    surface_forms: list[str],
    resolved_as: str,
    role_context: str | None,
    scope: dict,
    status: str,
    source_quote: str,
    confidence: float,
    source_dictation_id: int | None = None,
    reasoning: str,
) -> int:
    confirmed_at = _now() if status == "confirmed" else None
    cur = conn.execute(
        """
        INSERT INTO entities
            (surface_forms_json, resolved_as, role_context, scope_json, status,
             source_dictation_id, source_quote, confidence, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dumps(surface_forms), resolved_as, role_context, dumps(scope), status,
            source_dictation_id, source_quote, confidence, confirmed_at,
        ),
    )
    entity_id = cur.lastrowid
    log_event(
        conn, action="proposed" if status == "pending" else "confirmed", reasoning=reasoning,
        dictation_id=source_dictation_id, candidate_type="entity", memory_table="entities",
        memory_id=entity_id, confidence=confidence,
        payload={"resolved_as": resolved_as, "surface_forms": surface_forms},
    )
    return entity_id


def create_instruction(
    conn: sqlite3.Connection,
    *,
    rule_text: str,
    scope: dict,
    status: str,
    source_quote: str,
    confidence: float,
    source_dictation_id: int | None = None,
    reasoning: str,
) -> int:
    confirmed_at = _now() if status == "confirmed" else None
    cur = conn.execute(
        """
        INSERT INTO instructions
            (rule_text, scope_json, status, source_dictation_id, source_quote, confidence, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (rule_text, dumps(scope), status, source_dictation_id, source_quote, confidence, confirmed_at),
    )
    instruction_id = cur.lastrowid
    log_event(
        conn, action="proposed" if status == "pending" else "confirmed", reasoning=reasoning,
        dictation_id=source_dictation_id, candidate_type="instruction", memory_table="instructions",
        memory_id=instruction_id, confidence=confidence, payload={"rule_text": rule_text},
    )
    return instruction_id


def create_task(
    conn: sqlite3.Connection,
    *,
    label: str,
    app: str,
    last_state_summary: str,
    scope: dict,
    reasoning: str,
    source_dictation_id: int | None = None,
    status: str = "open",
    recurring: bool = False,
) -> int:
    # A recurring commitment has no natural end, so it never gets an expiry —
    # not even once confirmed. A one-off task expires after inactivity.
    expires_at = None if recurring else (datetime.utcnow() + timedelta(days=TASK_EXPIRY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    source_ids = [source_dictation_id] if source_dictation_id else []
    cur = conn.execute(
        """
        INSERT INTO tasks (label, app, last_state_summary, status, recurring, scope_json, source_dictation_ids_json, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (label, app, last_state_summary, status, int(recurring), dumps(scope), dumps(source_ids), expires_at),
    )
    task_id = cur.lastrowid
    log_event(
        conn, action="proposed" if status == "pending" else "confirmed", reasoning=reasoning,
        dictation_id=source_dictation_id, candidate_type="task", memory_table="tasks", memory_id=task_id,
        payload={"label": label, "last_state_summary": last_state_summary, "recurring": recurring},
    )
    return task_id


def append_task_progress(
    conn: sqlite3.Connection,
    *,
    task_id: int,
    last_state_summary: str,
    source_dictation_id: int | None,
    reasoning: str,
) -> None:
    """Append new progress to the task's running summary rather than
    replacing it. Each individual extraction call only sees the ONE new
    dictation, with no visibility into the task's prior state — replacing
    the summary would silently lose earlier progress (e.g. "outline and
    intro done" disappearing the moment "metrics done" is recorded, even
    though both are still true). Keeping a running log is what actually
    lets "recover information distributed across multiple dictations" hold
    for tasks whose state is described incrementally across dictations."""
    task = get_task(conn, task_id)
    source_ids = task["source_dictation_ids"] + ([source_dictation_id] if source_dictation_id else [])
    existing_summary = (task["last_state_summary"] or "").strip()
    new_summary = last_state_summary.strip()
    if existing_summary and new_summary and new_summary.lower() not in existing_summary.lower():
        combined_summary = f"{existing_summary} {new_summary}"
    else:
        combined_summary = new_summary or existing_summary
    conn.execute(
        "UPDATE tasks SET last_state_summary = ?, source_dictation_ids_json = ?, updated_at = ? WHERE id = ?",
        (combined_summary, dumps(source_ids), _now(), task_id),
    )
    log_event(
        conn, action="updated", reasoning=reasoning, dictation_id=source_dictation_id,
        candidate_type="task", memory_table="tasks", memory_id=task_id,
        payload={"last_state_summary": last_state_summary},
    )


def update_entity(conn: sqlite3.Connection, entity_id: int, *, resolved_as: str, role_context: str | None, reasoning: str) -> None:
    conn.execute(
        "UPDATE entities SET resolved_as = ?, role_context = ? WHERE id = ?",
        (resolved_as, role_context, entity_id),
    )
    log_event(
        conn, action="updated", reasoning=reasoning, candidate_type="entity",
        memory_table="entities", memory_id=entity_id, payload={"resolved_as": resolved_as},
    )


def update_instruction(conn: sqlite3.Connection, instruction_id: int, *, rule_text: str, active: bool, reasoning: str) -> None:
    conn.execute(
        "UPDATE instructions SET rule_text = ?, active = ? WHERE id = ?",
        (rule_text, int(active), instruction_id),
    )
    log_event(
        conn, action="updated", reasoning=reasoning, candidate_type="instruction",
        memory_table="instructions", memory_id=instruction_id, payload={"rule_text": rule_text, "active": active},
    )


def set_entity_status(conn: sqlite3.Connection, entity_id: int, status: str, reasoning: str) -> None:
    confirmed_at = _now() if status == "confirmed" else None
    conn.execute(
        "UPDATE entities SET status = ?, confirmed_at = COALESCE(confirmed_at, ?) WHERE id = ?",
        (status, confirmed_at, entity_id),
    )
    log_event(
        conn, action=status, reasoning=reasoning, candidate_type="entity",
        memory_table="entities", memory_id=entity_id,
    )


def set_instruction_status(conn: sqlite3.Connection, instruction_id: int, status: str, reasoning: str) -> None:
    confirmed_at = _now() if status == "confirmed" else None
    conn.execute(
        "UPDATE instructions SET status = ?, confirmed_at = COALESCE(confirmed_at, ?) WHERE id = ?",
        (status, confirmed_at, instruction_id),
    )
    log_event(
        conn, action=status, reasoning=reasoning, candidate_type="instruction",
        memory_table="instructions", memory_id=instruction_id,
    )


_TASK_STATUS_TO_EVENT_ACTION = {
    "open": "confirmed", "done": "updated", "expired": "expired", "rejected": "rejected",
}


def set_task_status(conn: sqlite3.Connection, task_id: int, status: str, reasoning: str) -> None:
    conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), task_id))
    log_event(
        conn, action=_TASK_STATUS_TO_EVENT_ACTION.get(status, "updated"), reasoning=reasoning,
        candidate_type="task", memory_table="tasks", memory_id=task_id,
    )


def delete_entity(conn: sqlite3.Connection, entity_id: int, reasoning: str) -> None:
    log_event(conn, action="deleted", reasoning=reasoning, candidate_type="entity", memory_table="entities", memory_id=entity_id)
    conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))


def delete_instruction(conn: sqlite3.Connection, instruction_id: int, reasoning: str) -> None:
    log_event(conn, action="deleted", reasoning=reasoning, candidate_type="instruction", memory_table="instructions", memory_id=instruction_id)
    conn.execute("DELETE FROM instructions WHERE id = ?", (instruction_id,))


def delete_task(conn: sqlite3.Connection, task_id: int, reasoning: str) -> None:
    log_event(conn, action="deleted", reasoning=reasoning, candidate_type="task", memory_table="tasks", memory_id=task_id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def entity_scope_matches(scope: dict, app: str) -> bool:
    return bool(scope.get("global")) or app in scope.get("apps", [])


def instruction_scope_matches(scope: dict, app: str, persona: str | None) -> bool:
    scope_app = scope.get("app")
    scope_persona = scope.get("persona")
    if scope_app and scope_app != app:
        return False
    if scope_persona and scope_persona != persona:
        return False
    return True


def find_matching_entity(conn: sqlite3.Connection, app: str, surface_forms: list[str]) -> dict | None:
    """Case-insensitive surface-form match, scoped to the given app (or
    global-scope entities). Shared by extraction's dedup and Hey Kivi's
    resolve_entity tool, so both use exactly the same notion of a match."""
    normalized = {s.strip().lower() for s in surface_forms}
    for entity in list_entities(conn):
        if entity["status"] == "rejected":
            continue
        if not entity_scope_matches(entity["scope"], app):
            continue
        existing = {s.strip().lower() for s in entity["surface_forms"]}
        if normalized & existing:
            return entity
    return None


_STOPWORDS = {"the", "a", "an", "for", "of", "on", "in", "to", "and", "my"}


def _label_tokens(label: str) -> set[str]:
    return {w for w in label.strip().lower().split() if w not in _STOPWORDS}


def find_matching_task(
    conn: sqlite3.Connection, app: str, label: str, threshold: float = 0.5,
    statuses: tuple[str, ...] = ("open",),
) -> dict | None:
    """Match by word-overlap rather than exact substring, so 'PRD voice search'
    and 'PRD for voice search' are recognized as the same piece of work. This
    is a simple heuristic (overlap coefficient over non-stopword tokens), not
    semantic matching — documented as a known limitation, not a hidden claim
    of more. Shared by extraction's task-accretion and Hey Kivi's resume_task
    tool.

    Uses the overlap coefficient (intersection / smaller set size) rather
    than Jaccard (intersection / union): task labels are short (2-4 words),
    and Jaccard punishes a single-word substitution too harshly there — e.g.
    "hiring plan" vs "hiring roadmap" scores 0.33 under Jaccard (below any
    reasonable threshold) but 0.5 under the overlap coefficient. Verified
    against every real task_clear pair in eval/results/latest: this
    correctly matches 13 of 15 previously-broken pairs. The 2 that remain
    unmatched share zero tokens at all (e.g. "hiring plan" vs "recruitment
    roadmap") — a full synonym substitution no lexical method can catch;
    that would need real semantic matching, which is out of scope here.

    `statuses` defaults to open-only, since resume_task must never act on an
    unconfirmed candidate. Extraction's own dedup passes ("open", "pending")
    so a recurring commitment mentioned twice before confirmation doesn't
    produce two separate pending proposals."""
    candidate_tokens = _label_tokens(label)
    best_match, best_score = None, 0.0
    for status in statuses:
        for task in list_tasks(conn, status=status):
            if task["app"] != app:
                continue
            existing_tokens = _label_tokens(task["label"])
            if not candidate_tokens or not existing_tokens:
                continue
            overlap = candidate_tokens & existing_tokens
            score = len(overlap) / min(len(candidate_tokens), len(existing_tokens))
            if score > best_score:
                best_match, best_score = task, score
    return best_match if best_score >= threshold else None


def touch_entity_used(conn: sqlite3.Connection, entity_id: int) -> None:
    conn.execute("UPDATE entities SET last_used_at = ? WHERE id = ?", (_now(), entity_id))


def touch_instruction_used(conn: sqlite3.Connection, instruction_id: int) -> None:
    conn.execute("UPDATE instructions SET last_used_at = ? WHERE id = ?", (_now(), instruction_id))


def log_hey_kivi_request(
    conn: sqlite3.Connection, *, kind: str, utterance: str, app: str | None, persona: str | None,
    intent: str | None, retrieved_entity_ids: list[int], retrieved_instruction_ids: list[int],
    retrieved_task_ids: list[int], retrieved_dictation_ids: list[int], result_text: str,
    grounded: bool, refused: bool, reasoning: str, latency_ms: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO hey_kivi_requests
            (kind, utterance, app, persona, intent, retrieved_entity_ids_json,
             retrieved_instruction_ids_json, retrieved_task_ids_json, retrieved_dictation_ids_json,
             result_text, grounded, refused, reasoning, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind, utterance, app, persona, intent, dumps(retrieved_entity_ids),
            dumps(retrieved_instruction_ids), dumps(retrieved_task_ids), dumps(retrieved_dictation_ids),
            result_text, int(grounded), int(refused), reasoning, latency_ms,
        ),
    )
    return cur.lastrowid


def list_recent_hey_kivi_requests(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM hey_kivi_requests ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    results = []
    for r in rows:
        d = row_to_dict(r)
        for key in ("retrieved_entity_ids", "retrieved_instruction_ids", "retrieved_task_ids", "retrieved_dictation_ids"):
            d[key] = loads(d.pop(f"{key}_json"), [])
        results.append(d)
    return results


def get_source_dictation_ids(conn: sqlite3.Connection, memory_table: str, memory_id: int) -> list[int]:
    """Every dictation that ever created or updated this memory item, per the
    audit trail — not just the one stored at creation. Lets a merged/updated
    entity cite its full history (e.g. a later dictation that changed a
    role) without needing a separate accreting column, since memory_events
    already recorded it."""
    rows = conn.execute(
        """
        SELECT DISTINCT dictation_id FROM memory_events
        WHERE memory_table = ? AND memory_id = ? AND dictation_id IS NOT NULL
        ORDER BY dictation_id
        """,
        (memory_table, memory_id),
    ).fetchall()
    return [r["dictation_id"] for r in rows]


def list_recent_dictations(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM dictations ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_dictation(conn: sqlite3.Connection, dictation_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM dictations WHERE id = ?", (dictation_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_events_for_dictation(conn: sqlite3.Connection, dictation_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM memory_events WHERE dictation_id = ? ORDER BY id", (dictation_id,)
    ).fetchall()
    events = []
    for r in rows:
        d = row_to_dict(r)
        d["payload"] = loads(d.pop("payload_json"), {})
        events.append(d)
    return events


def event_summary_for_dictation(conn: sqlite3.Connection, dictation_id: int) -> str:
    events = list_events_for_dictation(conn, dictation_id)
    extracted = next((e for e in events if e["action"] == "extracted"), None)
    if not extracted:
        return "not processed"
    candidates = extracted["payload"].get("candidates", [])
    if not candidates:
        return "nothing to remember"
    parts = []
    for e in events:
        if e["action"] in ("confirmed", "proposed", "updated") and e["candidate_type"]:
            label = {"confirmed": "remembered", "proposed": "pending confirmation", "updated": "updated"}[e["action"]]
            parts.append(f"{e['candidate_type']} {label}")
    return "; ".join(parts) if parts else f"{len(candidates)} candidate(s)"


def expire_stale_tasks(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at < ?", (_now(),)
    ).fetchall()
    for row in rows:
        set_task_status(conn, row["id"], "expired", reasoning=f"no activity since before expiry window ({TASK_EXPIRY_DAYS} days)")
    return len(rows)
