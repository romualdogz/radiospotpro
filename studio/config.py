"""Studio-Konfiguration – nur aus Umgebungsvariablen (bzw. .env), unabhängig vom Konfigurator."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config import _load_dotenv  # gemeinsamer .env-Loader (keine Datenbank, keine Seiteneffekte)

BASE_DIR = Path(__file__).resolve().parent
_load_dotenv(BASE_DIR.parent / ".env")


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "ja", "on")


def _list(name: str) -> list[str]:
    return [h.strip() for h in os.getenv(name, "").split(",") if h.strip()]


@dataclass(frozen=True)
class StudioSettings:
    database_url: str = os.getenv("STUDIO_DATABASE_URL", "sqlite:///./studio.db")
    # Eigener Schlüssel, damit Konfigurator-Cookies im Studio nichts gelten (und umgekehrt)
    secret_key: str = os.getenv("STUDIO_SECRET_KEY", "") or ("studio:" + os.getenv("SECRET_KEY", "dev-secret-change-me"))
    # Erstes Admin-Konto – wird nur angelegt, wenn es noch keinen Studio-Admin gibt
    admin_email: str = os.getenv("STUDIO_ADMIN_EMAIL", "admin@localhost").strip().lower()
    admin_password: str = os.getenv("STUDIO_ADMIN_PASSWORD", "")
    # Erlaubte Hostnamen, z. B. studio.onaircraft.net (leer = alle, für lokale Entwicklung)
    allowed_hosts: list[str] = field(default_factory=lambda: _list("STUDIO_HOSTS"))
    # Öffentliche Adresse für Einladungslinks (leer = Adresse der aktuellen Anfrage)
    public_url: str = os.getenv("STUDIO_PUBLIC_URL", "").rstrip("/")
    https_only: bool = _flag("STUDIO_HTTPS_ONLY", "0")
    session_hours: int = int(os.getenv("STUDIO_SESSION_HOURS", "12"))
    invite_days: int = int(os.getenv("STUDIO_INVITE_DAYS", "7"))
    # Fehlversuche pro IP bzw. E-Mail in 15 Minuten, danach Sperre
    login_attempts: int = int(os.getenv("STUDIO_LOGIN_ATTEMPTS", "8"))
    media_dir: Path = Path(os.getenv("STUDIO_MEDIA_DIR", str(BASE_DIR.parent / "media" / "studio")))


settings = StudioSettings()
