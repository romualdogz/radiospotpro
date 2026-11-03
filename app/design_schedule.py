"""Zeitplan für Designs – Admin → Design → „Zeitplan“.

Ein Eintrag schaltet von „Von“ bis „Bis“ (Ortszeit Wien) automatisch auf eine Layout-Variante um, z. B.
„Black Friday“ vom 27.11. bis 30.11. Außerhalb aller Zeiträume gilt das normal gespeicherte Design.
Gespeichert wird nur der Zeitplan; das normale Design bleibt unverändert.
"""
import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from . import theme
from .models import Setting

KEY = "design_schedule"
MAX_ENTRIES = 30
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Vienna")
except Exception:  # noqa: BLE001 – ohne Zeitzonen-Daten gilt die Uhrzeit des Servers
    TZ = None


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None) if TZ else datetime.now()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace(" ", "T")[:16])


def get_entries(db: Session) -> list[dict]:
    row = db.get(Setting, KEY)
    try:
        entries = json.loads(row.value) if row else []
    except ValueError:
        entries = []
    return sorted([e for e in entries if e.get("variant") in theme.VARIANTS], key=lambda e: e["start"])


def _save(db: Session, entries: list[dict]) -> None:
    db.merge(Setting(key=KEY, value=json.dumps(entries, ensure_ascii=False)))
    db.commit()


def add_entry(db: Session, start: str, end: str, variant: str, colors: bool, label: str = "") -> None:
    if variant not in theme.VARIANTS:
        raise ValueError("Bitte eine Layout-Variante wählen.")
    try:
        s, e = _parse(start), _parse(end)
    except ValueError as err:
        raise ValueError("Bitte „Von“ und „Bis“ mit Datum und Uhrzeit angeben.") from err
    if e <= s:
        raise ValueError("„Bis“ muss nach „Von“ liegen.")
    entries = get_entries(db)
    if len(entries) >= MAX_ENTRIES:
        raise ValueError(f"Höchstens {MAX_ENTRIES} Einträge – bitte alte löschen.")
    entries.append({"id": uuid.uuid4().hex[:8], "start": s.isoformat(timespec="minutes"),
                    "end": e.isoformat(timespec="minutes"), "variant": variant,
                    "colors": bool(colors and theme.VARIANTS[variant]["colors"]),
                    "label": " ".join(label.split())[:60]})
    _save(db, entries)


def remove_entry(db: Session, entry_id: str) -> None:
    _save(db, [e for e in get_entries(db) if e["id"] != entry_id])


def active_entry(db: Session, at: datetime | None = None) -> dict | None:
    at = at or now_local()
    current = [e for e in get_entries(db) if _parse(e["start"]) <= at < _parse(e["end"])]
    return current[-1] if current else None  # bei Überschneidung gilt der zuletzt beginnende


def status(entry: dict, at: datetime | None = None) -> str:
    at = at or now_local()
    if at < _parse(entry["start"]):
        return "geplant"
    return "aktiv" if at < _parse(entry["end"]) else "abgelaufen"


def apply(db: Session, design: dict, at: datetime | None = None) -> dict:
    """Gespeichertes Design + aktiver Zeitplan-Eintrag (falls einer gilt)."""
    entry = active_entry(db, at)
    if entry is None:
        return design
    design = {**design, **theme.variant_layout(entry["variant"])}
    if entry["colors"]:
        design.update(theme.PRESETS[theme.VARIANTS[entry["variant"]]["colors"]])
    return design
