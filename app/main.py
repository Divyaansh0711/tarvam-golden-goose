import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from app.db import get_db  # noqa: E402  (after load_dotenv, before use)
from app.routers import dictations, memory  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

app = FastAPI(title="Kivi — Semantic Memory")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.include_router(memory.router)
app.include_router(dictations.router)


@app.get("/healthz")
def healthz():
    with get_db() as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    return {"status": "ok", "tables": tables}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.post("/reset")
def reset():
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "reset.py"), "--seed"],
        cwd=PROJECT_ROOT, check=True,
    )
    return RedirectResponse("/", status_code=303)
