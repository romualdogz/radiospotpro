"""Konten und Einladungen – keine öffentliche Registrierung, nur Admin-Anlage oder Einladungslink."""
import logging
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from .config import settings
from .models import ROLES, Invitation, StudioUser, aware, now
from .security import hash_password, new_token, password_problem, token_hash

log = logging.getLogger("studio")


class AccountError(ValueError):
    pass


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or len(email) > 254 or " " in email:
        raise AccountError("Bitte eine gültige E-Mail-Adresse angeben.")
    return email


def check_role(role: str) -> str:
    if role not in ROLES:
        raise AccountError("Unbekannte Rolle.")
    return role


def create_user(db: Session, email: str, password: str, role: str = "pro", name: str = "") -> StudioUser:
    email, role = normalize_email(email), check_role(role)
    if problem := password_problem(password, email):
        raise AccountError(problem)
    if db.query(StudioUser).filter_by(email=email).first():
        raise AccountError("Für diese E-Mail-Adresse gibt es bereits ein Konto.")
    user = StudioUser(email=email, name=name.strip()[:120], password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    return user


def set_password(db: Session, user: StudioUser, password: str) -> None:
    if problem := password_problem(password, user.email):
        raise AccountError(problem)
    user.password_hash = hash_password(password)
    user.session_epoch += 1  # alle anderen Sessions abmelden
    db.commit()


def active_admins(db: Session) -> int:
    return db.query(StudioUser).filter_by(role="admin", active=True).count()


def update_user(db: Session, actor: StudioUser, user: StudioUser, *, role: str, active: bool,
                quota_mb: int, export_limit: int | None, name: str,
                tts_chars_month: int | None = ..., scripts_month: int | None = ...,
                valid_until=..., plan: str = ..., billing_note: str = ...) -> None:
    role = check_role(role)
    losing_admin = user.role == "admin" and user.active and (role != "admin" or not active)
    if losing_admin and active_admins(db) <= 1:
        raise AccountError("Der letzte aktive Administrator kann nicht herabgestuft oder gesperrt werden.")
    if user.id == actor.id and not active:
        raise AccountError("Du kannst dein eigenes Konto nicht sperren.")
    limits = [export_limit] + [v for v in (tts_chars_month, scripts_month) if v is not ...]
    if quota_mb < 0 or any(v is not None and v < 0 for v in limits):
        raise AccountError("Kontingente dürfen nicht negativ sein.")
    if not active or role != user.role:
        user.session_epoch += 1  # Rechte geändert → neu anmelden
    user.role, user.active, user.quota_mb, user.export_limit = role, active, quota_mb, export_limit
    user.name = name.strip()[:120]
    if tts_chars_month is not ...:
        user.tts_chars_month = tts_chars_month
    if scripts_month is not ...:
        user.scripts_month = scripts_month
    if valid_until is not ...:
        user.valid_until = valid_until
    if plan is not ...:
        user.plan = plan.strip()[:80]
    if billing_note is not ...:
        user.billing_note = billing_note.strip()[:4000]
    db.commit()


def create_invitation(db: Session, actor: StudioUser | None, email: str, role: str = "pro") -> tuple[Invitation, str]:
    email, role = normalize_email(email), check_role(role)
    if db.query(StudioUser).filter_by(email=email).first():
        raise AccountError("Für diese E-Mail-Adresse gibt es bereits ein Konto.")
    token, digest = new_token()
    inv = Invitation(token_hash=digest, email=email, role=role, created_by_id=actor.id if actor else None,
                     expires_at=now() + timedelta(days=settings.invite_days))
    db.add(inv)
    db.commit()
    return inv, token


def open_invitation(db: Session, token: str) -> Invitation | None:
    inv = db.query(Invitation).filter_by(token_hash=token_hash(token)).first()
    if inv is None or inv.revoked or inv.used_at or aware(inv.expires_at) < now():
        return None
    return inv


def accept_invitation(db: Session, token: str, password: str, name: str = "") -> StudioUser:
    inv = open_invitation(db, token)
    if inv is None:
        raise AccountError("Dieser Einladungslink ist ungültig oder abgelaufen.")
    user = create_user(db, inv.email, password, inv.role, name)
    if user.role == "trial":  # Testzugang läuft automatisch ab
        user.valid_until = now() + timedelta(days=settings.trial_days)
    inv.used_at = now()
    db.commit()
    return user


def ensure_admin(db: Session) -> None:
    """Erstes Admin-Konto anlegen. Ohne STUDIO_ADMIN_PASSWORD wird ein Zufallspasswort einmalig ins Log geschrieben."""
    if db.query(StudioUser).filter_by(role="admin").first():
        return
    password = settings.admin_password
    if not password:
        password = secrets.token_urlsafe(12)
        log.warning("Studio: Admin-Konto %s angelegt, Passwort: %s – bitte nach dem ersten Login ändern.",
                    settings.admin_email, password)
    db.add(StudioUser(email=settings.admin_email, role="admin",
                      password_hash=hash_password(password)))
    db.commit()


def check_active(user: StudioUser) -> None:
    """Abgelaufene Konten dürfen ansehen und herunterladen, aber nichts Neues erzeugen."""
    if user.expired():
        raise AccountError(f"Dein Zugang ist am {aware(user.valid_until):%d.%m.%Y} abgelaufen – "
                           "bitte onaircraft kontaktieren, um ihn zu verlängern.")
