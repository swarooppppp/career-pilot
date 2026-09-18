"""Application factory and top-level FastAPI routes."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.match import router as match_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.profile import router as profile_router
from app.api.routes.resume import router as resume_router


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "app" / "static"
TEMPLATE_PATH = ROOT / "app" / "templates" / "index.html"

app = FastAPI(title="Career Pilot", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(match_router, prefix="/api/match", tags=["match"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
app.include_router(profile_router, prefix="/api/profile", tags=["profile"])
app.include_router(resume_router, prefix="/api/resume", tags=["resume"])


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
