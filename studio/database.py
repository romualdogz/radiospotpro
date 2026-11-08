from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Spalten, die nach der ersten Version dazugekommen sind (create_all ergänzt keine Spalten in bestehenden Tabellen)
_ADDED_COLUMNS = [
    ("studio_users", "tts_chars_month", "INTEGER DEFAULT 20000"),
    ("studio_users", "scripts_month", "INTEGER DEFAULT 100"),
    ("studio_assets", "origin", "VARCHAR(10) NOT NULL DEFAULT 'upload'"),
]


def init_db() -> None:
    from . import models  # noqa: F401  (Tabellen registrieren)
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
