from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_db
from app.services import memory_store as store
from app.services.extraction import ingest_dictation

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

EXAMPLE_TRANSCRIPTS = [
    {
        "app": "slack", "raw_asr": "ask aditya to review the sarvam kiwi service",
        "formatted_text": "Ask Aditya to review the Sarvam Kiwi service.",
    },
    {
        "app": "email", "raw_asr": "always cc my manager on client emails",
        "formatted_text": "Always CC my manager on client emails.",
    },
    {
        "app": "docs", "raw_asr": "im drafting the prd for voice search v2 outline and intro are done still need the metrics section",
        "formatted_text": "I'm drafting the PRD for voice search v2. Outline and intro are done, still need the metrics section.",
    },
    {
        "app": "slack", "raw_asr": "remind me to grab coffee later",
        "formatted_text": "Remind me to grab coffee later.",
    },
]


@router.get("/dictations", response_class=HTMLResponse)
def dictations_page(request: Request, highlight: int | None = None):
    with get_db() as conn:
        recent = store.list_recent_dictations(conn)
        summaries = {d["id"]: store.event_summary_for_dictation(conn, d["id"]) for d in recent}
        highlight_events = store.list_events_for_dictation(conn, highlight) if highlight else []
        highlight_dictation = store.get_dictation(conn, highlight) if highlight else None
    return templates.TemplateResponse(
        "dictation_feed.html",
        {
            "request": request, "recent": recent, "summaries": summaries,
            "highlight_dictation": highlight_dictation, "highlight_events": highlight_events,
            "examples": EXAMPLE_TRANSCRIPTS,
        },
    )


@router.post("/dictations")
def submit_dictation(app: str = Form(...), raw_asr: str = Form(...), formatted_text: str = Form(...)):
    with get_db() as conn:
        dictation_id, _outcomes = ingest_dictation(
            conn, app=app, occurred_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            raw_asr=raw_asr, formatted_text=formatted_text, metadata={}, source="manual",
        )
    return RedirectResponse(f"/dictations?highlight={dictation_id}", status_code=303)
