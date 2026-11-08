"""Radiospot-Studio – eigenständige App (eigener Server, eigene Datenbank, eigenes Login).

Start:  uvicorn studio.main:app --port 8001
    /               Studio (nur angemeldet)
    /login          Anmeldung – es gibt keine öffentliche Registrierung
    /invite/<token> Konto über Einladungslink einrichten
    /admin/users    Konten, Rollen, Kontingente, Einladungen (nur Administratoren)
    /api/...        JSON-API (jede Route verlangt eine gültige Session)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import api, pages
from .accounts import ensure_admin
from .config import BASE_DIR, settings
from .database import SessionLocal, init_db
from .security import Forbidden, LoginRequired

_CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ensure_admin(db)
    yield


app = FastAPI(title="Radiospot-Studio", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # API-Beschreibung nicht öffentlich


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("Content-Security-Policy", _CSP)
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")  # Einladungs-Token nie per Referer weitergeben
    if not request.url.path.startswith("/static/"):
        h.setdefault("Cache-Control", "no-store")
    if settings.https_only:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="studio_session",  # eigenes Cookie, gilt nur für den Studio-Host
    same_site="lax",
    https_only=settings.https_only,
    max_age=settings.session_hours * 3600,
)
if settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(pages.router)
app.include_router(api.router)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, exc: Forbidden):
    return pages.render(request, "forbidden.html", 403, user=exc.user)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
