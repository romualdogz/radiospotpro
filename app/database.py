from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Spalten, die nach der ersten Version dazugekommen sind: (Tabelle, Spalte, SQL-Definition).
# create_all legt nur neue Tabellen an – fehlende Spalten in bestehenden Datenbanken ergänzen wir hier.
_ADDED_COLUMNS = [
    ("addons", "requires_studio", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("stations", "kind", "VARCHAR(20) NOT NULL DEFAULT 'radio'"),
    ("stations", "ad_tax_applies", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("quote_requests", "street", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("quote_requests", "zip_code", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("quote_requests", "city", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("voices", "elevenlabs_voice_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("music_styles", "audio_file", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("voices", "stability_bp", "INTEGER NOT NULL DEFAULT 5000"),
    ("voices", "similarity_bp", "INTEGER NOT NULL DEFAULT 7500"),
    ("voices", "style_bp", "INTEGER NOT NULL DEFAULT 0"),
    ("voices", "speed_bp", "INTEGER NOT NULL DEFAULT 10000"),
    ("tonalities", "stability_bp", "INTEGER"),
    ("tonalities", "style_bp", "INTEGER"),
    ("tonalities", "speed_bp", "INTEGER"),
    ("tonalities", "delivery_hint", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("quote_requests", "consent", "JSON NOT NULL DEFAULT '{}'"),
    ("admin_users", "role", "VARCHAR(20) NOT NULL DEFAULT 'admin'"),
    ("quote_requests", "mail_log", "JSON NOT NULL DEFAULT '[]'"),
    ("music_styles", "gain_bp", "INTEGER NOT NULL DEFAULT 10000"),
    ("stations", "coverage_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("packages", "coverage_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("stations", "map_color", "VARCHAR(7) NOT NULL DEFAULT ''"),
    ("coverage_areas", "color", "VARCHAR(7) NOT NULL DEFAULT ''"),
    ("packages", "station_ids", "JSON NOT NULL DEFAULT '[]'"),
    ("packages", "station_mode", "VARCHAR(10) NOT NULL DEFAULT 'choose'"),
    ("packages", "article_no", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("packages", "duration_days", "INTEGER NOT NULL DEFAULT 0"),
    ("packages", "recommended_days", "INTEGER NOT NULL DEFAULT 0"),
    ("packages", "studio_bookable", "BOOLEAN NOT NULL DEFAULT 1"),
]


def upgrade_schema() -> None:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
