"""HTML-Seiten des Studios: Anmeldung, Einladung, Arbeitsfläche, Konto, Benutzerverwaltung."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .accounts import (AccountError, accept_invitation, create_invitation, open_invitation, set_password,
                       update_user)
from .config import BASE_DIR, settings
from .database import get_db
from . import ai
from . import storage
from .models import LIBRARY_CATEGORIES, ROLES, Invitation, Library, LibraryItem, Project, StudioUser, StudioVoice
from .security import (authenticate, check_csrf, client_ip, csrf_token, current_user, page_admin, page_user,
                       start_session, throttle, touch_login, verify_password)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["roles"] = ROLES
templates.env.globals["categories"] = LIBRARY_CATEGORIES


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("user", None)
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, template, {"csrf": csrf_token(request), "flash": flash, **ctx},
                                      status_code=status_code)


def redirect(url: str, flash: str | None = None, request: Request | None = None) -> RedirectResponse:
    if flash and request is not None:
        request.session["flash"] = flash
    return RedirectResponse(url, status_code=303)


# --------------------------------------------------------------------------- Anmeldung

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/")
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(""),
          db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    keys = ("ip:" + client_ip(request), "mail:" + email.strip().lower())
    if throttle.blocked(*keys):
        return render(request, "login.html", 429, email=email,
                      error="Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.")
    user = authenticate(db, email, password)
    if user is None:
        throttle.fail(*keys)
        return render(request, "login.html", 401, email=email, error="E-Mail oder Passwort falsch.")
    throttle.reset(keys[1])
    start_session(request, user)
    touch_login(db, user)
    return redirect("/")


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return redirect("/login")


# --------------------------------------------------------------------------- Einladung

@router.get("/invite/{token}", response_class=HTMLResponse)
def invite_form(token: str, request: Request, db: Session = Depends(get_db)):
    inv = open_invitation(db, token)
    return render(request, "invite.html", 200 if inv else 404, invitation=inv, error=None)


@router.post("/invite/{token}")
def invite_accept(token: str, request: Request, name: str = Form(""), password: str = Form(...),
                  password2: str = Form(...), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    inv = open_invitation(db, token)
    if inv is None:
        return render(request, "invite.html", 404, invitation=None, error=None)
    if password != password2:
        return render(request, "invite.html", 400, invitation=inv, name=name,
                      error="Die beiden Passwörter stimmen nicht überein.")
    try:
        user = accept_invitation(db, token, password, name)
    except AccountError as e:
        return render(request, "invite.html", 400, invitation=inv, name=name, error=str(e))
    start_session(request, user)
    touch_login(db, user)
    return redirect("/", "Willkommen im Studio! Dein Konto ist eingerichtet.", request)


# --------------------------------------------------------------------------- Arbeitsfläche

@router.get("/", response_class=HTMLResponse)
def studio(request: Request, user: StudioUser = Depends(page_user)):
    return render(request, "studio.html", user=user, export_days=settings.export_days)


# --------------------------------------------------------------------------- Mein Konto

@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user: StudioUser = Depends(page_user)):
    return render(request, "account.html", user=user, error=None)


@router.post("/account/password")
def change_password(request: Request, current: str = Form(...), password: str = Form(...),
                    password2: str = Form(...), csrf: str = Form(""),
                    user: StudioUser = Depends(page_user), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    error = None
    if not verify_password(current, user.password_hash):
        error = "Das aktuelle Passwort ist falsch."
    elif password != password2:
        error = "Die beiden neuen Passwörter stimmen nicht überein."
    else:
        try:
            set_password(db, user, password)
        except AccountError as e:
            error = str(e)
    if error:
        return render(request, "account.html", 400, user=user, error=error)
    start_session(request, user)  # diese Session bleibt angemeldet, alle anderen nicht
    return redirect("/account", "Passwort geändert. Andere Geräte wurden abgemeldet.", request)


# --------------------------------------------------------------------------- Benutzerverwaltung (nur Admin)

def _invite_url(request: Request, token: str) -> str:
    base = settings.public_url or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


def _users_page(request: Request, user: StudioUser, db: Session, error: str | None = None):
    return render(request, "users.html", 400 if error else 200, user=user, error=error,
                  users=db.query(StudioUser).order_by(StudioUser.email).all(),
                  invitations=db.query(Invitation).order_by(Invitation.created_at.desc()).limit(50).all(),
                  private_libs=db.query(Library).filter_by(for_all=False).order_by(Library.name).all(),
                  new_link=request.session.pop("new_invite", None))


@router.get("/admin/users", response_class=HTMLResponse)
def users(request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    return _users_page(request, user, db)


@router.post("/admin/invitations")
def invite(request: Request, email: str = Form(...), role: str = Form("pro"), csrf: str = Form(""),
           user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    try:
        inv, token = create_invitation(db, user, email, role)
    except AccountError as e:
        return _users_page(request, user, db, error=str(e))
    request.session["new_invite"] = {"email": inv.email, "url": _invite_url(request, token)}
    return redirect("/admin/users")


@router.post("/admin/invitations/{inv_id}/revoke")
def revoke(inv_id: int, request: Request, csrf: str = Form(""),
           user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    inv = db.get(Invitation, inv_id)
    if inv and not inv.used_at:
        inv.revoked = True
        db.commit()
    return redirect("/admin/users", "Einladung widerrufen.", request)


def _opt_int(value: str) -> int | None:
    return int(value) if value.strip() else None


@router.post("/admin/users/{user_id}")
def edit_user(user_id: int, request: Request, role: str = Form(...), active: str = Form(""),
              quota_mb: int = Form(0), export_limit: str = Form(""), name: str = Form(""), csrf: str = Form(""),
              tts_chars_month: str = Form(""), scripts_month: str = Form(""), libraries: list[int] = Form([]),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    target = db.get(StudioUser, user_id)
    if target is None:
        return redirect("/admin/users", "Konto nicht gefunden.", request)
    try:
        update_user(db, user, target, role=role, active=bool(active), quota_mb=quota_mb,
                    export_limit=_opt_int(export_limit), name=name,
                    tts_chars_month=_opt_int(tts_chars_month), scripts_month=_opt_int(scripts_month))
        target.libraries = sorted({i for i in libraries if db.get(Library, i)})
        db.commit()
    except ValueError as e:  # AccountError oder ungültige Zahl
        db.rollback()
        msg = str(e) if isinstance(e, AccountError) else "Bitte gültige Zahlen angeben."
        return _users_page(request, user, db, error=msg)
    if target.id == user.id:
        start_session(request, target)  # eigene Rolle geändert – Session neu ausstellen
    return redirect("/admin/users", f"Konto {target.email} gespeichert.", request)


# --------------------------------------------------------------------------- KI-Stimmen (nur Admin)

def _voices_page(request: Request, user: StudioUser, db: Session, error: str | None = None, refresh: bool = False):
    voices = db.query(StudioVoice).order_by(StudioVoice.sort, StudioVoice.name).all()
    taken = {v.elevenlabs_voice_id for v in voices}
    account = [v for v in ai.account_voices(force=refresh) if v["id"] not in taken]
    return render(request, "voices.html", 400 if error else 200, user=user, error=error, voices=voices,
                  account=account, tts=ai.voice_enabled(), tags=ai.tags_supported())


@router.get("/admin/voices", response_class=HTMLResponse)
def voices(request: Request, refresh: int = 0, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    return _voices_page(request, user, db, refresh=bool(refresh))


def _voice_values(name: str, voice_id: str, description: str, stability: float, similarity: float,
                  style: float, speed: float, sort: int) -> dict:
    name, voice_id = name.strip(), voice_id.strip()
    if not name or not voice_id:
        raise ValueError("Name und ElevenLabs-Voice-ID sind Pflicht.")
    if not all(c.isalnum() for c in voice_id) or len(voice_id) > 64:
        raise ValueError("Die Voice-ID besteht nur aus Buchstaben und Ziffern.")
    clamp = lambda v, lo, hi: min(max(float(v), lo), hi)  # noqa: E731
    return {"name": name[:80], "elevenlabs_voice_id": voice_id, "description": description.strip()[:255],
            "stability": clamp(stability, 0, 1), "similarity": clamp(similarity, 0, 1),
            "style": clamp(style, 0, 1), "speed": clamp(speed, 0.7, 1.2), "sort": sort}


@router.post("/admin/voices")
def add_voice(request: Request, name: str = Form(""), voice_id: str = Form(""), account_voice_id: str = Form(""),
              description: str = Form(""),
              stability: float = Form(0.5), similarity: float = Form(0.75), style: float = Form(0.0),
              speed: float = Form(1.0), sort: int = Form(0), csrf: str = Form(""),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    voice_id = voice_id.strip() or account_voice_id.strip()
    if not name.strip():  # aus der Kontoliste gewählt: Name übernehmen
        name = next((v["name"] for v in ai.account_voices() if v["id"] == voice_id.strip()), "")
    try:
        values = _voice_values(name, voice_id, description, stability, similarity, style, speed, sort)
    except ValueError as e:
        return _voices_page(request, user, db, error=str(e))
    db.add(StudioVoice(**values))
    db.commit()
    return redirect("/admin/voices", f"Stimme „{values['name']}“ freigegeben.", request)


@router.post("/admin/voices/{vid}")
def edit_voice(vid: int, request: Request, name: str = Form(""), voice_id: str = Form(""),
               description: str = Form(""), stability: float = Form(0.5), similarity: float = Form(0.75),
               style: float = Form(0.0), speed: float = Form(1.0), sort: int = Form(0), active: str = Form(""),
               csrf: str = Form(""), user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    voice = db.get(StudioVoice, vid)
    if voice is None:
        return redirect("/admin/voices", "Stimme nicht gefunden.", request)
    try:
        values = _voice_values(name, voice_id, description, stability, similarity, style, speed, sort)
    except ValueError as e:
        return _voices_page(request, user, db, error=str(e))
    for k, v in values.items():
        setattr(voice, k, v)
    voice.active = bool(active)
    db.commit()
    return redirect("/admin/voices", f"Stimme „{voice.name}“ gespeichert.", request)


@router.post("/admin/voices/{vid}/delete")
def delete_voice(vid: int, request: Request, csrf: str = Form(""),
                 user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    voice = db.get(StudioVoice, vid)
    if voice:
        db.delete(voice)
        db.commit()
    return redirect("/admin/voices", "Stimme entfernt. Bereits erzeugte Aufnahmen bleiben erhalten.", request)


# --------------------------------------------------------------------------- Bibliothek (nur Admin)

def _usage_count(db: Session) -> dict[int, int]:
    """Wie oft jede Bibliotheksdatei in Projekten verwendet wird."""
    counts: dict[int, int] = {}
    for (data,) in db.query(Project.data):
        for c in (data or {}).get("clips", []):
            if c.get("lib_id") is not None:
                counts[c["lib_id"]] = counts.get(c["lib_id"], 0) + 1
    return counts


@router.get("/admin/library", response_class=HTMLResponse)
def libraries(request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    libs = db.query(Library).order_by(Library.name).all()
    counts = {lib.id: db.query(LibraryItem).filter_by(library_id=lib.id).count() for lib in libs}
    return render(request, "libraries.html", user=user, libs=libs, counts=counts, error=None)


def _lib_values(name: str, description: str, for_all: str, license_note: str) -> dict:
    if not name.strip():
        raise ValueError("Bitte einen Namen angeben.")
    return {"name": name.strip()[:120], "description": description.strip()[:255], "for_all": bool(for_all),
            "license_note": license_note.strip()[:500]}


@router.post("/admin/library")
def add_library(request: Request, name: str = Form(""), description: str = Form(""), for_all: str = Form(""),
                license_note: str = Form(""), csrf: str = Form(""),
                user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    try:
        lib = Library(**_lib_values(name, description, for_all, license_note))
    except ValueError as e:
        return redirect("/admin/library", str(e), request)
    db.add(lib)
    db.commit()
    return redirect(f"/admin/library/{lib.id}", f"Bibliothek „{lib.name}“ angelegt – jetzt Dateien hochladen.", request)


def _lib_or_404(db: Session, lib_id: int) -> Library:
    from fastapi import HTTPException
    lib = db.get(Library, lib_id)
    if lib is None:
        raise HTTPException(404, "Bibliothek nicht gefunden")
    return lib


def _library_page(request: Request, user: StudioUser, db: Session, lib: Library, error: str | None = None,
                  status: int = 200):
    items = db.query(LibraryItem).filter_by(library_id=lib.id).order_by(LibraryItem.category, LibraryItem.name).all()
    return render(request, "library.html", status, user=user, lib=lib, items=items, used=_usage_count(db),
                  error=error, max_mb=storage.settings.max_upload_mb)


@router.get("/admin/library/{lib_id}", response_class=HTMLResponse)
def library_page(lib_id: int, request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    return _library_page(request, user, db, _lib_or_404(db, lib_id))


@router.post("/admin/library/{lib_id}")
def edit_library(lib_id: int, request: Request, name: str = Form(""), description: str = Form(""),
                 for_all: str = Form(""), license_note: str = Form(""), csrf: str = Form(""),
                 user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    lib = _lib_or_404(db, lib_id)
    try:
        for k, v in _lib_values(name, description, for_all, license_note).items():
            setattr(lib, k, v)
    except ValueError as e:
        db.rollback()
        return _library_page(request, user, db, lib, str(e), 400)
    db.commit()
    return redirect(f"/admin/library/{lib.id}", "Bibliothek gespeichert.", request)


@router.post("/admin/library/{lib_id}/delete")
def delete_library(lib_id: int, request: Request, csrf: str = Form(""),
                   user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    lib = _lib_or_404(db, lib_id)
    items = db.query(LibraryItem).filter_by(library_id=lib.id).all()
    used = _usage_count(db)
    if any(used.get(i.id) for i in items):
        return _library_page(request, user, db, lib, "Dateien dieser Bibliothek werden in Projekten verwendet – "
                             "bitte stattdessen einzelne Dateien deaktivieren.", 409)
    for item in items:
        storage.delete_library_item(db, item)
    db.delete(lib)
    db.commit()
    return redirect("/admin/library", f"Bibliothek „{lib.name}“ gelöscht.", request)


@router.post("/admin/library/{lib_id}/upload")
async def upload_library(lib_id: int, request: Request, files: list[UploadFile] = File(...),
                         category: str = Form("sfx"), tags: str = Form(""), license_note: str = Form(""),
                         csrf: str = Form(""), user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    lib = _lib_or_404(db, lib_id)
    if category not in LIBRARY_CATEGORIES:
        category = "sfx"
    limit = storage.settings.max_upload_mb * 1024 * 1024
    added, errors = 0, []
    for f in files:
        tmp = storage.library_dir() / (f"tmp-{user.id}-" + __import__("secrets").token_hex(8) + ".part")
        try:
            storage.check_upload_name(f.filename or "")
            size = 0
            with tmp.open("wb") as out:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise storage.StorageError(f"größer als {storage.settings.max_upload_mb} MB")
                    out.write(chunk)
            await run_in_threadpool(storage.add_library_item, db, lib.id, f.filename or "", tmp, category, tags, license_note)
            added += 1
        except storage.StorageError as e:
            errors.append(f"{f.filename}: {e}")
        finally:
            tmp.unlink(missing_ok=True)
    msg = f"{added} Datei(en) hinzugefügt." + (" Nicht übernommen – " + "; ".join(errors) if errors else "")
    return redirect(f"/admin/library/{lib.id}", msg, request)


@router.post("/admin/library/items/{item_id}")
def edit_item(item_id: int, request: Request, name: str = Form(""), category: str = Form("sfx"), tags: str = Form(""),
              license_note: str = Form(""), active: str = Form(""), csrf: str = Form(""),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    item = db.get(LibraryItem, item_id)
    if item is None:
        return redirect("/admin/library", "Datei nicht gefunden.", request)
    if name.strip():
        item.name = name.strip()[:200]
    item.category = category if category in LIBRARY_CATEGORIES else item.category
    item.tags, item.license_note, item.active = tags.strip()[:300], license_note.strip()[:500], bool(active)
    db.commit()
    return redirect(f"/admin/library/{item.library_id}", f"„{item.name}“ gespeichert.", request)


@router.post("/admin/library/items/{item_id}/delete")
def delete_item(item_id: int, request: Request, csrf: str = Form(""),
                user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    item = db.get(LibraryItem, item_id)
    if item is None:
        return redirect("/admin/library", "Datei nicht gefunden.", request)
    lib_id = item.library_id
    if _usage_count(db).get(item.id):
        return redirect(f"/admin/library/{lib_id}", f"„{item.name}“ wird in Projekten verwendet – stattdessen deaktivieren.", request)
    storage.delete_library_item(db, item)
    return redirect(f"/admin/library/{lib_id}", f"„{item.name}“ gelöscht.", request)
