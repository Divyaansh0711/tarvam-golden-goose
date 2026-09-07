from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_db
from app.services import memory_store as store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/memory", response_class=HTMLResponse)
def memory_page(request: Request):
    with get_db() as conn:
        store.expire_stale_tasks(conn)
        context = {
            "request": request,
            "entities_confirmed": store.list_entities(conn, "confirmed"),
            "entities_pending": store.list_entities(conn, "pending"),
            "instructions_confirmed": store.list_instructions(conn, "confirmed"),
            "instructions_pending": store.list_instructions(conn, "pending"),
            "tasks_open": store.list_tasks(conn, "open"),
            "tasks_pending": store.list_tasks(conn, "pending"),
            "tasks_done": store.list_tasks(conn, "done"),
        }
    return templates.TemplateResponse("memory.html", context)


# --- Entities -----------------------------------------------------------

@router.post("/memory/entities")
def add_entity(
    surface_forms: str = Form(...),
    resolved_as: str = Form(...),
    role_context: str = Form(""),
    app: str = Form(""),
):
    scope = {"apps": [app]} if app else {"global": True}
    with get_db() as conn:
        store.create_entity(
            conn,
            surface_forms=[s.strip() for s in surface_forms.split(",") if s.strip()],
            resolved_as=resolved_as,
            role_context=role_context or None,
            scope=scope,
            status="confirmed",
            source_quote="(added directly by the user on the Memory screen)",
            confidence=1.0,
            reasoning="manually added by the user — direct action, no extraction involved",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/entities/{entity_id}/update")
def update_entity(entity_id: int, resolved_as: str = Form(...), role_context: str = Form("")):
    with get_db() as conn:
        store.update_entity(
            conn, entity_id, resolved_as=resolved_as, role_context=role_context or None,
            reasoning="edited by the user on the Memory screen",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/entities/{entity_id}/confirm")
def confirm_entity(entity_id: int):
    with get_db() as conn:
        store.set_entity_status(conn, entity_id, "confirmed", reasoning="confirmed by the user from the pending inbox")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/entities/{entity_id}/reject")
def reject_entity(entity_id: int):
    with get_db() as conn:
        store.set_entity_status(conn, entity_id, "rejected", reasoning="dismissed by the user from the pending inbox")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/entities/{entity_id}/delete")
def delete_entity(entity_id: int):
    with get_db() as conn:
        store.delete_entity(conn, entity_id, reasoning="deleted by the user on the Memory screen")
    return RedirectResponse("/memory", status_code=303)


# --- Instructions ---------------------------------------------------------

@router.post("/memory/instructions")
def add_instruction(rule_text: str = Form(...), app: str = Form(""), persona: str = Form("")):
    scope = {k: v for k, v in {"app": app or None, "persona": persona or None}.items() if v}
    with get_db() as conn:
        store.create_instruction(
            conn, rule_text=rule_text, scope=scope, status="confirmed",
            source_quote="(added directly by the user on the Memory screen)", confidence=1.0,
            reasoning="manually added by the user — direct action, no extraction involved",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/instructions/{instruction_id}/update")
def update_instruction(instruction_id: int, rule_text: str = Form(...), active: str = Form("on")):
    with get_db() as conn:
        store.update_instruction(
            conn, instruction_id, rule_text=rule_text, active=(active == "on"),
            reasoning="edited by the user on the Memory screen",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/instructions/{instruction_id}/confirm")
def confirm_instruction(instruction_id: int):
    with get_db() as conn:
        store.set_instruction_status(conn, instruction_id, "confirmed", reasoning="confirmed by the user from the pending inbox")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/instructions/{instruction_id}/reject")
def reject_instruction(instruction_id: int):
    with get_db() as conn:
        store.set_instruction_status(conn, instruction_id, "rejected", reasoning="dismissed by the user from the pending inbox")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/instructions/{instruction_id}/delete")
def delete_instruction(instruction_id: int):
    with get_db() as conn:
        store.delete_instruction(conn, instruction_id, reasoning="deleted by the user on the Memory screen")
    return RedirectResponse("/memory", status_code=303)


# --- Tasks ------------------------------------------------------------

@router.post("/memory/tasks")
def add_task(label: str = Form(...), app: str = Form(...), last_state_summary: str = Form(...)):
    with get_db() as conn:
        store.create_task(
            conn, label=label, app=app, last_state_summary=last_state_summary, scope={"apps": [app]},
            reasoning="manually added by the user — direct action, no extraction involved",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/tasks/{task_id}/update")
def update_task(task_id: int, last_state_summary: str = Form(...)):
    with get_db() as conn:
        store.append_task_progress(
            conn, task_id=task_id, last_state_summary=last_state_summary,
            source_dictation_id=None, reasoning="edited by the user on the Memory screen",
        )
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/tasks/{task_id}/done")
def complete_task(task_id: int):
    with get_db() as conn:
        store.set_task_status(conn, task_id, "done", reasoning="marked done by the user")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/tasks/{task_id}/confirm")
def confirm_task(task_id: int):
    with get_db() as conn:
        store.set_task_status(conn, task_id, "open", reasoning="confirmed as a permanent recurring commitment by the user")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/tasks/{task_id}/reject")
def reject_task(task_id: int):
    with get_db() as conn:
        store.set_task_status(conn, task_id, "rejected", reasoning="dismissed by the user from the pending inbox")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/tasks/{task_id}/delete")
def delete_task(task_id: int):
    with get_db() as conn:
        store.delete_task(conn, task_id, reasoning="deleted by the user on the Memory screen")
    return RedirectResponse("/memory", status_code=303)
