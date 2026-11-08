from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

ROLES = {"admin": "Administrator", "pro": "Pro", "trial": "Testzugang"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite liefert Zeitstempel ohne Zeitzone zurück – als UTC behandeln."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class StudioUser(Base):
    __tablename__ = "studio_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="pro")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Wird bei Passwortwechsel/Sperre erhöht – alle bestehenden Sessions werden damit ungültig
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    # Kontingente pro Konto (werden ab Schritt 2 durchgesetzt); None = unbegrenzt
    quota_mb: Mapped[int] = mapped_column(Integer, default=2000)
    export_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    libraries: Mapped[list] = mapped_column(JSON, default=list)
    # KI-Kontingente pro Kalendermonat; None = unbegrenzt
    tts_chars_month: Mapped[int | None] = mapped_column(Integer, nullable=True, default=20000)
    scripts_month: Mapped[int | None] = mapped_column(Integer, nullable=True, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invitation(Base):
    __tablename__ = "studio_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nur der SHA-256 des Tokens wird gespeichert – der Link selbst ist nach dem Anlegen nicht mehr abrufbar
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20), default="pro")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("studio_users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    def status(self) -> str:
        if self.revoked:
            return "widerrufen"
        if self.used_at:
            return "eingelöst"
        if aware(self.expires_at) < now():
            return "abgelaufen"
        return "offen"


TRACKS = {"voice": "Sprache", "music": "Musik", "sfx": "SFX", "atmo": "Atmo"}


class Asset(Base):
    """Hochgeladene Audiodatei eines Nutzers (Sprecheraufnahme, Musik, Geräusch …)."""
    __tablename__ = "studio_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("studio_users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(80))  # Dateiname auf der Platte (zufällig)
    media_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    origin: Mapped[str] = mapped_column(String(10), default="upload")  # upload | ai
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Base):
    __tablename__ = "studio_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("studio_users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # {"length": 30, "tracks": {"voice": {"gain_db": 0, "mute": false, "solo": false}, …}, "clips": [...]}
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Export(Base):
    """Render-Auftrag. Läuft im Worker, nie im Webprozess."""
    __tablename__ = "studio_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("studio_users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("studio_projects.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # Projektstand beim Auftrag
    loudness: Mapped[float | None] = mapped_column(Float, nullable=True)  # Ziel-LUFS, None = nur Spitzen begrenzen
    # queued → running → done | failed; done → expired (Datei gelöscht)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    stored_name: Mapped[str] = mapped_column(String(80), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    measured_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudioVoice(Base):
    """KI-Stimme, die der Admin für das Studio freigibt (ElevenLabs)."""
    __tablename__ = "studio_voices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(255), default="")
    elevenlabs_voice_id: Mapped[str] = mapped_column(String(64))
    stability: Mapped[float] = mapped_column(Float, default=0.5)
    similarity: Mapped[float] = mapped_column(Float, default=0.75)
    style: Mapped[float] = mapped_column(Float, default=0.0)   # nur ältere Modelle ohne Regieanweisungen
    speed: Mapped[float] = mapped_column(Float, default=1.0)   # dito
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AiUsage(Base):
    """Verbrauch der KI-Funktionen (für Monatskontingente und Übersicht)."""
    __tablename__ = "studio_ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("studio_users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # script | voice
    chars: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


LIBRARY_CATEGORIES = {"sfx": "SFX", "music": "Musik", "atmo": "Atmo"}


class Library(Base):
    """Von onaircraft gepflegte Sammlung (SFX, Musik, Atmo), die Studio-Nutzer verwenden dürfen."""
    __tablename__ = "studio_libraries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(255), default="")
    # True = alle Konten; sonst nur Konten, deren `libraries` die ID enthält
    for_all: Mapped[bool] = mapped_column(Boolean, default=True)
    # Lizenzhinweis, gilt für alle Dateien dieser Sammlung (sofern die Datei keinen eigenen hat)
    license_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LibraryItem(Base):
    __tablename__ = "studio_library_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("studio_libraries.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(10), default="sfx")
    tags: Mapped[str] = mapped_column(String(300), default="")
    license_note: Mapped[str] = mapped_column(String(500), default="")
    stored_name: Mapped[str] = mapped_column(String(80))
    media_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    # Inaktiv = nicht mehr in der Auswahl, bestehende Projekte klingen aber weiter gleich
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
