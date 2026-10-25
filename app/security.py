"""Admin-Authentifizierung: Passwort-Hashing (scrypt), Session-Login, HTTP-Basic für die API, CSRF."""
import base64
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .models import AdminUser

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


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


def authenticate(db: Session, username: str, password: str) -> AdminUser | None:
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if user and verify_password(password, user.password_hash):
        return user
    # Konstante Laufzeit auch bei unbekanntem Benutzer
    if user is None:
        verify_password(password, hash_password("dummy"))
    return None


def current_admin_or_none(request: Request, db: Session) -> AdminUser | None:
    user_id = request.session.get("admin_id")
    return db.get(AdminUser, user_id) if user_id else None


_basic = HTTPBasic(auto_error=False)


def require_admin_api(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    db: Session = Depends(get_db),
) -> AdminUser:
    """Admin-API: akzeptiert eingeloggte Admin-Session oder HTTP Basic Auth."""
    user = current_admin_or_none(request, db)
    if user is None and credentials is not None:
        user = authenticate(db, credentials.username, credentials.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin-Login erforderlich",
            headers={"WWW-Authenticate": "Basic"},
        )
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur für Administratoren")
    return user


# --------------------------------------------------------------------------- CSRF (für HTML-Formulare)

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=400, detail="Ungültiges CSRF-Token – bitte Seite neu laden.")
