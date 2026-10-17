"""Application factory and top-level FastAPI routes."""

from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.logging_utils import configure_logging
from app.services.batch_scheduler import start_batch_scheduler
from app.api.routes.match import router as match_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.profile import router as profile_router
from app.api.routes.resume import router as resume_router


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "app" / "static"
TEMPLATE_PATH = ROOT / "app" / "templates" / "index.html"

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        if not os.getenv("SESSION_SECRET") or not os.getenv("APP_PASSWORD"):
            raise RuntimeError("SESSION_SECRET and APP_PASSWORD are required in production")
    stop_scheduler = start_batch_scheduler()
    try:
        yield
    finally:
        stop_scheduler.set()


app = FastAPI(title="Career Pilot", version="0.1.0", lifespan=lifespan)
session_secret = os.getenv("SESSION_SECRET", "")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret or "local-development-only-secret",
    https_only=os.getenv("ENVIRONMENT", "development").lower() == "production",
    same_site="lax",
)


@app.middleware("http")
async def require_login(request: Request, call_next):
    password = os.getenv("APP_PASSWORD", "")
    if not password or request.url.path in {"/health", "/login", "/logout"} or request.url.path.startswith("/static/"):
        return await call_next(request)
    if request.session.get("authenticated"):
        return await call_next(request)
    return RedirectResponse("/login", status_code=303)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(match_router, prefix="/api/match", tags=["match"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
app.include_router(profile_router, prefix="/api/profile", tags=["profile"])
app.include_router(resume_router, prefix="/api/resume", tags=["resume"])


@app.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return """<!doctype html><title>Career Pilot login</title><form method=post><h1>Career Pilot</h1><input name=password type=password placeholder=Password autofocus required><button>Sign in</button></form>"""


@app.post("/login")
async def login(request: Request) -> RedirectResponse:
    submitted = parse_qs((await request.body()).decode("utf-8")).get("password", [""])[0]
    expected = os.getenv("APP_PASSWORD", "")
    if expected and hmac.compare_digest(submitted, expected):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
