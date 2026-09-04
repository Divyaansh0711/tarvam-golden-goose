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
) -> int:
    expires_at = (datetime.utcnow() + timedelta(days=TASK_EXPIRY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    source_ids = [source_dictation_id] if source_dictation_id else []
    cur = conn.execute(
        """
        INSERT INTO tasks (label, app, last_state_summary, scope_json, source_dictation_ids_json, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (label, app, last_state_summary, dumps(scope), dumps(source_ids), expires_at),
    )
    task_id = cur.lastrowid
    log_event(
        conn, action="confirmed", reasoning=reasoning, dictation_id=source_dictation_id,
        candidate_type="task", memory_table="tasks", memory_id=task_id,
        payload={"label": label, "last_state_summary": last_state_summary},
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
    task = get_task(conn, task_id)
    source_ids = task["source_dictation_ids"] + ([source_dictation_id] if source_dictation_id else [])
    conn.execute(
        "UPDATE tasks SET last_state_summary = ?, source_dictation_ids_json = ?, updated_at = ? WHERE id = ?",
        (last_state_summary, dumps(source_ids), _now(), task_id),
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


def set_task_status(conn: sqlite3.Connection, task_id: int, status: str, reasoning: str) -> None:
    conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), task_id))
    log_event(
        conn, action=status, reasoning=reasoning, candidate_type="task",
        memory_table="tasks", memory_id=task_id,
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


def expire_stale_tasks(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at < ?", (_now(),)
    ).fetchall()
    for row in rows:
        set_task_status(conn, row["id"], "expired", reasoning=f"no activity since before expiry window ({TASK_EXPIRY_DAYS} days)")
    return len(rows)
