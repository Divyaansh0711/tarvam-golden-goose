from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_db
from app.services import memory_store as store
from app.services.hey_kivi import handle_request

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

EXAMPLE_REQUESTS = [
    {"app": "slack", "utterance": "Message Rahul about the launch timing."},
    {"app": "email", "utterance": "Draft a follow-up email to the client."},
    {"app": "docs", "utterance": "Keep working on the PRD for voice search."},
    {"app": "slack", "utterance": "Message Priya about the launch timing."},
    {"app": "slack", "utterance": "What's Rahul's role?"},
    {"app": "docs", "utterance": "What's the current state of the PRD?"},
    {"app": "docs", "utterance": "What's my favorite color?"},
    {"app": "docs", "utterance": "What's the weather like today?"},
]


def _resolve_citations(conn, req: dict) -> dict:
    return {
        "entities": [store.get_entity(conn, eid) for eid in req["retrieved_entity_ids"]],
        "instructions": [store.get_instruction(conn, iid) for iid in req["retrieved_instruction_ids"]],
        "tasks": [store.get_task(conn, tid) for tid in req["retrieved_task_ids"]],
        "dictations": [store.get_dictation(conn, did) for did in req["retrieved_dictation_ids"]],
    }


@router.get("/hey-kivi", response_class=HTMLResponse)
def hey_kivi_page(request: Request, highlight: int | None = None):
    with get_db() as conn:
        recent = store.list_recent_hey_kivi_requests(conn)
        highlight_request = next((r for r in recent if r["id"] == highlight), None) if highlight else None
        citations = _resolve_citations(conn, highlight_request) if highlight_request else None
    return templates.TemplateResponse(
        "hey_kivi.html",
        {
            "request": request, "recent": recent, "highlight_request": highlight_request,
            "citations": citations, "examples": EXAMPLE_REQUESTS,
        },
    )


@router.post("/hey-kivi")
def submit_request(utterance: str = Form(...), app: str = Form(...), persona: str = Form("")):
    with get_db() as conn:
        request_id = handle_request(conn, utterance=utterance, app=app, persona=persona or None)
    return RedirectResponse(f"/hey-kivi?highlight={request_id}", status_code=303)
