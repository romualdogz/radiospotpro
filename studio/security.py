"""Studio-Zugang: Passwörter (scrypt), Sessions mit Ablauf, Rollen, CSRF, Sperre nach Fehlversuchen.

Grundregel: Jede Route prüft serverseitig. Seiten leiten ohne Login zur Anmeldung um,
API-Routen antworten mit 401/403 – eine versteckte Adresse allein schützt nichts.
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import StudioUser, now

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSWORD = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(digest, expected)


_DUMMY_HASH = hash_password(secrets.token_hex(8))


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Das Passwort muss mindestens {MIN_PASSWORD} Zeichen haben."
    if email and password.lower() == email.lower():
        return "Das Passwort darf nicht der E-Mail-Adresse entsprechen."
    return None


def authenticate(db: Session, email: str, password: str) -> StudioUser | None:
    user = db.query(StudioUser).filter(StudioUser.email == email.strip().lower()).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)  # gleiche Laufzeit wie bei bekanntem Konto
        return None
    if not verify_password(password, user.password_hash) or not user.active:
        return None
    return user


# --------------------------------------------------------------------------- Sperre nach Fehlversuchen

class LoginThrottle:
    """Zählt Fehlversuche je Schlüssel (IP bzw. E-Mail) in einem gleitenden Zeitfenster (im Speicher)."""

    def __init__(self, window: int = 15 * 60):
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        self._hits[key] = hits
        return hits

    def blocked(self, *keys: str) -> bool:
        with self._lock:
            return any(len(self._recent(k)) >= settings.login_attempts for k in keys)

    def fail(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._recent(k).append(time.monotonic())

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._hits.pop(k, None)


throttle = LoginThrottle()


def client_ip(request: Request) -> str:
    # Hinter einem Reverse-Proxy uvicorn mit --proxy-headers starten, dann steht hier die echte IP
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- Sessions

def start_session(request: Request, user: StudioUser) -> None:
    request.session.clear()
    request.session.update({"uid": user.id, "epoch": user.session_epoch,
                            "exp": int(time.time()) + settings.session_hours * 3600})


def current_user(request: Request, db: Session) -> StudioUser | None:
    s = request.session
    uid, exp = s.get("uid"), s.get("exp", 0)
    if not uid or exp < time.time():
        return None
    user = db.get(StudioUser, uid)
    if user is None or not user.active or user.session_epoch != s.get("epoch"):
        return None
    return user


class LoginRequired(Exception):
    """Seite ohne gültige Session → Weiterleitung zur Anmeldung."""


class Forbidden(Exception):
    def __init__(self, user: StudioUser):
        self.user = user


def page_user(request: Request, db: Session = Depends(get_db)) -> StudioUser:
    user = current_user(request, db)
    if user is None:
        request.session.clear()
        raise LoginRequired()
    return user


def page_admin(user: StudioUser = Depends(page_user)) -> StudioUser:
    if user.role != "admin":
        raise Forbidden(user)
    return user


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def api_user(request: Request, db: Session = Depends(get_db)) -> StudioUser:
    """Für alle /api-Routen: gültige Session, bei schreibenden Anfragen zusätzlich der CSRF-Header."""
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Anmeldung erforderlich")
    if request.method not in _SAFE_METHODS:
        check_csrf(request, request.headers.get("X-CSRF-Token"))
    return user


def api_admin(user: StudioUser = Depends(api_user)) -> StudioUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return user


# --------------------------------------------------------------------------- CSRF

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ungültiges CSRF-Token – bitte Seite neu laden.")


# --------------------------------------------------------------------------- Einladungen

def new_token() -> tuple[str, str]:
    """(Token für den Link, SHA-256 für die Datenbank)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def touch_login(db: Session, user: StudioUser) -> None:
    user.last_login_at = now()
    db.commit()
