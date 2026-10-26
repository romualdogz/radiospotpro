"""FastAPI-Einstiegspunkt.

Start:  uvicorn app.main:app --reload
    /               Konfigurator (Beispiel-Frontend, kann durch eigenes ersetzt werden)
    /admin          Admin-Oberfläche
    /docs           OpenAPI-Dokumentation
"""
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import BASE_DIR, settings
from .database import SessionLocal, get_db, upgrade_schema
from . import branding, fonts, theme
from .models import LegalText
from .security import current_admin_or_none
from .routers import admin_api, admin_ui, public
from .seed import (
    apply_tonality_presets, attach_demo_music, ensure_admin, ensure_countries, ensure_legal_texts, ensure_example_packages, seed_demo_data, ensure_coverage_areas, ensure_station_colors,
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
        ensure_station_colors(db)
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
# Eigene Google-Fonts aus dem Admin, einmalig vom Server heruntergeladen (keine Verbindung der Besucher zu Google)
fonts.CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/fonts", StaticFiles(directory=str(fonts.CUSTOM_DIR)), name="fonts")
app.include_router(public.router)
app.include_router(admin_api.router)
app.include_router(admin_ui.router)


@app.exception_handler(admin_ui._LoginRequired)
async def _login_required(request: Request, _exc):
    return RedirectResponse("/admin/login", status_code=303)


@app.exception_handler(admin_ui._Forbidden)
async def _forbidden(request: Request, exc):
    return admin_ui.forbidden_page(request, exc.user)


def _design(request: Request, db: Session) -> tuple[dict, str]:
    """Gespeichertes Design – für eingeloggte Admins mit Live-Vorschau aus dem Layout-Designer
    (?preset=…&layout_…=…, wird nicht gespeichert). Liefert zusätzlich den Query-String für /theme.css."""
    design = theme.get_theme(db)
    q = request.query_params
    keys = [k for k in q if k.startswith("layout_") or k == "preset"]
    if not keys or current_admin_or_none(request, db) is None:
        return design, ""
    design.update(theme.PRESETS.get(q.get("preset", ""), {}))
    design.update(theme.validate_layout({**design, **q}))
    return design, "&" + urlencode({k: q[k] for k in keys})


def _page_context(request: Request, db: Session) -> dict:
    design, preview_qs = _design(request, db)
    return {"fonts_url": theme.fonts_url(design), "theme_version": theme.version(design) + preview_qs,
            "logo": branding.get_logo(db), "design": design, "body_class": theme.body_class(design)}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def configurator(request: Request, db: Session = Depends(get_db)):
    return admin_ui.templates.TemplateResponse(request, "configurator.html", _page_context(request, db))


@app.get("/agb", response_class=HTMLResponse, include_in_schema=False)
@app.get("/datenschutz", response_class=HTMLResponse, include_in_schema=False)
def legal_page(request: Request, db: Session = Depends(get_db)):
    key = request.url.path.strip("/")
    text = db.query(LegalText).filter_by(key=key).first()
    return admin_ui.templates.TemplateResponse(request, "legal.html",
                                               {"text": text, **_page_context(request, db)})


@app.get("/media/logo/{name}", include_in_schema=False)
def logo_file(name: str):
    path = branding.logo_path(name)
    if path is None:
        return Response(status_code=404)
    # SVGs dürfen keine Skripte ausführen, auch wenn die Datei direkt geöffnet wird
    return Response(path.read_bytes(), media_type=branding.MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                    headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff",
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.get("/fonts.css", include_in_schema=False)
def fonts_css(db: Session = Depends(get_db)):
    css = fonts.css_for(theme.families(theme.get_theme(db)))
    return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/theme.css", include_in_schema=False)
def theme_css(request: Request, db: Session = Depends(get_db)):
    design, preview_qs = _design(request, db)
    return Response(theme.css(design), media_type="text/css",
                    headers={"Cache-Control": "no-store" if preview_qs else "public, max-age=300"})


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
