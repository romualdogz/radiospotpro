"""HTML-Seiten des Studios: Anmeldung, Einladung, Arbeitsfläche, Konto, Benutzerverwaltung."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .accounts import (AccountError, accept_invitation, create_invitation, open_invitation, set_password,
                       update_user)
from .config import BASE_DIR, settings
from .database import get_db
from .models import ROLES, Invitation, StudioUser
from .security import (authenticate, check_csrf, client_ip, csrf_token, current_user, page_admin, page_user,
                       start_session, throttle, touch_login, verify_password)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["roles"] = ROLES


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
    return render(request, "studio.html", user=user)


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


@router.post("/admin/users/{user_id}")
def edit_user(user_id: int, request: Request, role: str = Form(...), active: str = Form(""),
              quota_mb: int = Form(0), export_limit: str = Form(""), name: str = Form(""), csrf: str = Form(""),
              user: StudioUser = Depends(page_admin), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    target = db.get(StudioUser, user_id)
    if target is None:
        return redirect("/admin/users", "Konto nicht gefunden.", request)
    try:
        limit = int(export_limit) if export_limit.strip() else None
        update_user(db, user, target, role=role, active=bool(active), quota_mb=quota_mb,
                    export_limit=limit, name=name)
    except ValueError as e:  # AccountError oder ungültige Zahl
        db.rollback()
        msg = str(e) if isinstance(e, AccountError) else "Bitte gültige Zahlen angeben."
        return _users_page(request, user, db, error=msg)
    if target.id == user.id:
        start_session(request, target)  # eigene Rolle geändert – Session neu ausstellen
    return redirect("/admin/users", f"Konto {target.email} gespeichert.", request)
