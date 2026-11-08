from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
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
