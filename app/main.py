"""FastAPI-Einstiegspunkt.

Start:  uvicorn app.main:app --reload
    /               Konfigurator (Beispiel-Frontend, kann durch eigenes ersetzt werden)
    /admin          Admin-Oberfläche
    /docs           OpenAPI-Dokumentation
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import BASE_DIR, settings
from .database import SessionLocal, get_db, upgrade_schema
from . import branding, theme
from .models import LegalText
from .routers import admin_api, admin_ui, public
from .seed import (
    apply_tonality_presets, attach_demo_music, ensure_admin, ensure_countries, ensure_legal_texts, ensure_example_packages, seed_demo_data, ensure_coverage_areas,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade_schema()
    with SessionLocal() as db:
        ensure_admin(db)
        ensure_countries(db)
        ensure_legal_texts(db)
        ensure_example_packages(db)
        if settings.seed_demo_data:
            seed_demo_data(db)
            attach_demo_music(db)
            apply_tonality_presets(db)
        ensure_coverage_areas(db)  # nach den Demo-Daten, damit die Beispiel-Sender verknüpft werden
    yield


app = FastAPI(title="Radiospot-Konfigurator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="radiospot_admin",
    same_site="lax",
    https_only=False,  # in Produktion hinter HTTPS auf True setzen
    max_age=8 * 3600,
)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# Hochgeladene Musik (Vorhörfunktion im Konfigurator)
settings.media_dir.joinpath("music").mkdir(parents=True, exist_ok=True)
app.mount("/media/music", StaticFiles(directory=str(settings.media_dir / "music")), name="music")
app.include_router(public.router)
app.include_router(admin_api.router)
app.include_router(admin_ui.router)


@app.exception_handler(admin_ui._LoginRequired)
async def _login_required(request: Request, _exc):
    return RedirectResponse("/admin/login", status_code=303)


@app.exception_handler(admin_ui._Forbidden)
async def _forbidden(request: Request, exc):
    return admin_ui.forbidden_page(request, exc.user)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def configurator(request: Request, db: Session = Depends(get_db)):
    design = theme.get_theme(db)
    return admin_ui.templates.TemplateResponse(request, "configurator.html", {
        "fonts_url": theme.fonts_url(design), "theme_version": theme.version(design),
        "logo": branding.get_logo(db), "design": design})


@app.get("/agb", response_class=HTMLResponse, include_in_schema=False)
@app.get("/datenschutz", response_class=HTMLResponse, include_in_schema=False)
def legal_page(request: Request, db: Session = Depends(get_db)):
    key = request.url.path.strip("/")
    text = db.query(LegalText).filter_by(key=key).first()
    design = theme.get_theme(db)
    return admin_ui.templates.TemplateResponse(request, "legal.html", {
        "text": text, "fonts_url": theme.fonts_url(design), "theme_version": theme.version(design),
        "logo": branding.get_logo(db), "design": design})


@app.get("/media/logo/{name}", include_in_schema=False)
def logo_file(name: str):
    path = branding.logo_path(name)
    if path is None:
        return Response(status_code=404)
    # SVGs dürfen keine Skripte ausführen, auch wenn die Datei direkt geöffnet wird
    return Response(path.read_bytes(), media_type=branding.MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                    headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff",
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.get("/theme.css", include_in_schema=False)
def theme_css(db: Session = Depends(get_db)):
    return Response(theme.css(theme.get_theme(db)), media_type="text/css",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
