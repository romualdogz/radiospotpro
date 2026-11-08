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
from . import mail, storage, totp
from .accounts import AccountError as _AccountError
from .models import (LIBRARY_CATEGORIES, ROLES, AiUsage, Asset, Export, Invitation, Library, LibraryItem, Project,
                     StudioUser, StudioVoice, SupportRequest, aware, now)
from .security import (authenticate, check_csrf, client_ip, csrf_token, current_user, page_admin, page_user,
                       start_session, throttle, touch_login, verify_password)
import time
from datetime import datetime, timezone

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
    if user.totp_enabled and user.totp_secret:
        request.session.clear()
        request.session.update({"pending_uid": user.id, "pending_exp": int(time.time()) + 300})
        return redirect("/login/2fa")
    start_session(request, user)
    touch_login(db, user)
    return redirect("/")


def _pending_user(request: Request, db: Session) -> StudioUser | None:
    uid, exp = request.session.get("pending_uid"), request.session.get("pending_exp", 0)
    if not uid or exp < time.time():
        return None
    user = db.get(StudioUser, uid)
    return user if user and user.active and user.totp_enabled else None


@router.get("/login/2fa", response_class=HTMLResponse)
def login_2fa_form(request: Request, db: Session = Depends(get_db)):
    if _pending_user(request, db) is None:
        return redirect("/login")
    return render(request, "login_2fa.html", error=None)


@router.post("/login/2fa")
def login_2fa(request: Request, code: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = _pending_user(request, db)
    if user is None:
        return redirect("/login", "Anmeldung abgelaufen – bitte erneut anmelden.", request)
    keys = ("ip:" + client_ip(request), "mail:" + user.email)
    if throttle.blocked(*keys):
        return render(request, "login_2fa.html", 429, error="Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.")
    step = totp.verify(user.totp_secret, code, user.totp_last_step)
    if step is None:
        throttle.fail(*keys)
        return render(request, "login_2fa.html", 401, error="Der Code stimmt nicht. Bitte den aktuellen Code aus der App eingeben.")
    user.totp_last_step = step
    db.commit()
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

def _account_page(request: Request, user: StudioUser, error: str | None = None, status: int = 200):
    setup = None
    secret = request.session.get("totp_setup")
    if secret and not user.totp_enabled:
        setup = {"secret": secret, "qr": totp.qr_svg_data_uri(totp.uri(secret, user.email)),
                 "pretty": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))}
    return render(request, "account.html", status, user=user, error=error, setup=setup)


@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user: StudioUser = Depends(page_user)):
    return _account_page(request, user)


@router.post("/account/2fa/start")
def totp_start(request: Request, csrf: str = Form(""), user: StudioUser = Depends(page_user)):
    check_csrf(request, csrf)
    if not user.totp_enabled:
        request.session["totp_setup"] = totp.new_secret()
    return redirect("/account#zwei-faktor")


@router.post("/account/2fa/confirm")
def totp_confirm(request: Request, code: str = Form(""), csrf: str = Form(""),
                 user: StudioUser = Depends(page_user), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    secret = request.session.get("totp_setup")
    step = totp.verify(secret, code) if secret else None
    if step is None:
        return _account_page(request, user, "Der Code stimmt nicht – bitte den aktuellen Code aus der App eingeben.", 400)
    user.totp_secret, user.totp_enabled, user.totp_last_step = secret, True, step
    user.session_epoch += 1  # andere Geräte neu anmelden (jetzt mit zweitem Faktor)
    db.commit()
    request.session.pop("totp_setup", None)
    start_session(request, user)
    return redirect("/account", "Zwei-Faktor-Anmeldung ist eingeschaltet.", request)


@router.post("/account/2fa/disable")
def totp_disable(request: Request, password: str = Form(""), code: str = Form(""), csrf: str = Form(""),
                 user: StudioUser = Depends(page_user), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    if not verify_password(password, user.password_hash) or totp.verify(user.totp_secret or "", code, user.totp_last_step) is None:
        return _account_page(request, user, "Passwort oder Code stimmt nicht.", 400)
    user.totp_secret, user.totp_enabled, user.totp_last_step = None, False, None
    db.commit()
    return redirect("/account", "Zwei-Faktor-Anmeldung ist ausgeschaltet.", request)


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
        return _account_page(request, user, error, 400)
    start_session(request, user)  # diese Session bleibt angemeldet, alle anderen nicht
    return redirect("/account", "Passwort geändert. Andere Geräte wurden abgemeldet.", request)


# --------------------------------------------------------------------------- Benutzerverwaltung (nur Admin)

def _invite_url(request: Request, token: str) -> str:
    base = settings.public_url or str(request.base_url).rstrip("/")
    return f"{base}/invite/{token}"


def _usage_overview(db: Session) -> dict[int, dict]:
    from sqlalchemy import func
    from .ai import month_start
    out: dict[int, dict] = {}
    for uid, b in db.query(Asset.user_id, func.sum(Asset.size_bytes)).group_by(Asset.user_id):
        out.setdefault(uid, {})["bytes"] = int(b or 0)
    for uid, b in db.query(Export.user_id, func.sum(Export.size_bytes)).filter(Export.status == "done").group_by(Export.user_id):
        out.setdefault(uid, {})["bytes"] = out.get(uid, {}).get("bytes", 0) + int(b or 0)
    for uid, n in db.query(Export.user_id, func.count(Export.id)).group_by(Export.user_id):
        out.setdefault(uid, {})["exports"] = n
    for uid, c in (db.query(AiUsage.user_id, func.sum(AiUsage.chars)).filter(AiUsage.kind == "voice",
                   AiUsage.created_at >= month_start()).group_by(AiUsage.user_id)):
        out.setdefault(uid, {})["voice_chars"] = int(c or 0)
    return out


def _users_page(request: Request, user: StudioUser, db: Session, error: str | None = None):
    return render(request, "users.html", 400 if error else 200, user=user, error=error,
                  users=db.query(StudioUser).order_by(StudioUser.email).all(), usage=_usage_overview(db),
                  mail_enabled=mail.enabled(), now=now(), aware=aware,
                  invitations=db.query(Invitation).order_by(Invitation.created_at.desc()).limit(50).all(),
                  new_link=request.session.pop("new_invite", None))


@router.get("/admin/users/{user_id}", response_class=HTMLResponse)
def user_detail(user_id: int, request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    target = db.get(StudioUser, user_id)
    if target is None:
        return redirect("/admin/users", "Konto nicht gefunden.", request)
    return _user_detail_page(request, user, db, target)


def _user_detail_page(request: Request, user: StudioUser, db: Session, target: StudioUser,
                      error: str | None = None, status: int = 200):
    return render(request, "user_detail.html", status, user=user, target=target, error=error,
                  usage=_usage_overview(db).get(target.id, {}), aware=aware,
                  private_libs=db.query(Library).filter_by(for_all=False).order_by(Library.name).all())


@router.post("/admin/users/{user_id}/reset-2fa")
def reset_2fa(user_id: int, request: Request, csrf: str = Form(""),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    target = db.get(StudioUser, user_id)
    if target:
        target.totp_secret, target.totp_enabled, target.totp_last_step = None, False, None
        target.session_epoch += 1
        db.commit()
    return redirect(f"/admin/users/{user_id}", "Zwei-Faktor-Anmeldung zurückgesetzt – das Konto meldet sich jetzt nur mit Passwort an.", request)


@router.get("/admin/users", response_class=HTMLResponse)
def users(request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    return _users_page(request, user, db)


@router.post("/admin/invitations")
async def invite(request: Request, email: str = Form(...), role: str = Form("pro"), send_mail: str = Form(""),
                 csrf: str = Form(""), user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    try:
        inv, token = create_invitation(db, user, email, role)
    except AccountError as e:
        return _users_page(request, user, db, error=str(e))
    url = _invite_url(request, token)
    mailed, mail_error = False, ""
    if send_mail and mail.enabled():
        try:
            await run_in_threadpool(mail.send_invitation, inv.email, url, inv.role, inv.expires_at)
            mailed = True
        except Exception as e:  # noqa: BLE001 – Link bleibt sichtbar, Fehler wird angezeigt
            mail_error = str(e)
    request.session["new_invite"] = {"email": inv.email, "url": url, "mailed": mailed, "mail_error": mail_error}
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
              valid_until: str = Form(""), plan: str = Form(""), billing_note: str = Form(""),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    target = db.get(StudioUser, user_id)
    if target is None:
        return redirect("/admin/users", "Konto nicht gefunden.", request)
    try:
        until = (datetime.strptime(valid_until.strip(), "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
                 if valid_until.strip() else None)
        update_user(db, user, target, role=role, active=bool(active), quota_mb=quota_mb,
                    export_limit=_opt_int(export_limit), name=name,
                    tts_chars_month=_opt_int(tts_chars_month), scripts_month=_opt_int(scripts_month),
                    valid_until=until, plan=plan, billing_note=billing_note)
        target.libraries = sorted({i for i in libraries if db.get(Library, i)})
        db.commit()
    except ValueError as e:  # AccountError oder ungültige Zahl
        db.rollback()
        msg = str(e) if isinstance(e, AccountError) else "Bitte gültige Zahlen bzw. ein gültiges Datum angeben."
        return _user_detail_page(request, user, db, target, msg, 400)
    if target.id == user.id:
        start_session(request, target)  # eigene Rolle geändert – Session neu ausstellen
    return redirect(f"/admin/users/{target.id}", f"Konto {target.email} gespeichert.", request)


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


# --------------------------------------------------------------------------- An onaircraft geschickt (nur Admin)

@router.get("/admin/support", response_class=HTMLResponse)
def support_list(request: Request, user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    reqs = db.query(SupportRequest).order_by(SupportRequest.created_at.desc()).limit(200).all()
    users = {u.id: u for u in db.query(StudioUser)}
    return render(request, "support.html", user=user, reqs=reqs, users=users)


@router.post("/admin/support/{req_id}/status")
def support_status(req_id: int, request: Request, status: str = Form(...), csrf: str = Form(""),
                   user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    req = db.get(SupportRequest, req_id)
    if req and status in ("offen", "in Arbeit", "erledigt"):
        req.status = status
        db.commit()
    return redirect("/admin/support")


@router.post("/admin/support/{req_id}/copy")
def support_copy(req_id: int, request: Request, csrf: str = Form(""),
                 user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    """Projekt mit allen eigenen Dateien des Kunden ins Admin-Konto kopieren (Bibliotheksdateien bleiben Verweise)."""
    import shutil
    check_csrf(request, csrf)
    req = db.get(SupportRequest, req_id)
    if req is None:
        return redirect("/admin/support", "Anfrage nicht gefunden.", request)
    if req.copy_project_id and db.get(Project, req.copy_project_id):
        return redirect("/", f"Die Kopie „{db.get(Project, req.copy_project_id).name}“ liegt schon in deinen Projekten.", request)
    data = dict(req.snapshot or {})
    clips = [dict(c) for c in data.get("clips", [])]
    mapping: dict[int, int] = {}
    for c in clips:
        aid = c.get("asset_id")
        if aid is None or aid in mapping:
            continue
        src = db.get(Asset, aid)
        if src is None or src.user_id != req.user_id:
            continue
        copy = Asset(user_id=user.id, name=src.name, stored_name=src.stored_name, media_type=src.media_type,
                     size_bytes=src.size_bytes, duration_s=src.duration_s, origin=src.origin)
        dest = storage.user_dir(user.id, "assets") / src.stored_name
        shutil.copyfile(storage.asset_path(src), dest)
        if storage.peaks_path(src).exists():
            shutil.copyfile(storage.peaks_path(src), dest.with_suffix(".peaks.json"))
        db.add(copy)
        db.flush()
        mapping[aid] = copy.id
    clips = [c | {"asset_id": mapping[c["asset_id"]]} if c.get("asset_id") in mapping else c for c in clips
             if c.get("asset_id") is None or c.get("asset_id") in mapping]
    owner = db.get(StudioUser, req.user_id)
    project = Project(user_id=user.id, name=f"{owner.email if owner else 'Kunde'} – {req.project_name}"[:120],
                      data={**data, "clips": clips})
    db.add(project)
    db.flush()
    req.copy_project_id, req.status = project.id, "in Arbeit" if req.status == "offen" else req.status
    db.commit()
    return redirect("/", f"Kopie „{project.name}“ angelegt – im Projekt-Menü auswählen.", request)
