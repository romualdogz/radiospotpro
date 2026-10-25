"""Zentrale Konfiguration – wird ausschließlich aus Umgebungsvariablen gelesen."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimaler .env-Loader, damit keine zusätzliche Abhängigkeit nötig ist."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        # typische Kopierfehler abfangen: „NAME=NAME=wert“ und Anführungszeichen um den Wert
        while value.startswith(f"{key}="):
            value = value[len(key) + 1:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).resolve().parent
_load_dotenv(BASE_DIR.parent / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./radiospot.db")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
        ]
    )
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "1").strip().lower() in ("1", "true", "yes", "ja", "on")
    # Hochgeladene Musik und Hörproben-Cache
    media_dir: Path = Path(os.getenv("MEDIA_DIR", str(BASE_DIR.parent / "media")))


settings = Settings()
