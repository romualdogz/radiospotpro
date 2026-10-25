"""Lautstärke der Hintergrundmusik im Spot – einstellbar unter Admin → Einstellungen.

Die Werte gelten relativ zum Spitzenpegel der Musik (die Stimme liegt bei 90 %); je Musikstück
kann zusätzlich eine Lautstärke-Korrektur hinterlegt werden (Admin → Musik).
"""
from sqlalchemy.orm import Session

from .models import Setting

# Schlüssel → (Standard in %, Minimum, Maximum)
LEVELS = {
    "mix_bed_level": (14, 0, 60),    # Musik unter der Stimme
    "mix_open_level": (45, 0, 100),  # Musik ohne Stimme (Intro, Outro)
}


def get_levels(db: Session) -> dict[str, int]:
    stored = {s.key: s.value for s in db.query(Setting).filter(Setting.key.in_(list(LEVELS)))}
    out = {}
    for key, (default, lo, hi) in LEVELS.items():
        try:
            out[key] = min(hi, max(lo, int(stored.get(key, default))))
        except ValueError:
            out[key] = default
    return out


def save_levels(db: Session, values: dict[str, int]) -> None:
    for key, (_, lo, hi) in LEVELS.items():
        if key in values:
            db.merge(Setting(key=key, value=str(min(hi, max(lo, int(values[key]))))))
    db.commit()
