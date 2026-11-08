"""Projektformat (gemeinsam für Speichern, Vorhören im Browser und Rendern) und Prüfung."""
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from .config import settings
from .models import TRACKS, Asset

MAX_CLIPS = 300


class TrackState(BaseModel):
    gain_db: float = Field(0.0, ge=-60, le=12)
    mute: bool = False
    solo: bool = False


class Clip(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    asset_id: int
    track: str
    start: float = Field(ge=0)        # Position auf der Zeitleiste (s)
    offset: float = Field(0.0, ge=0)  # Beginn innerhalb der Datei (s)
    duration: float = Field(gt=0)     # hörbare Länge (s)
    gain_db: float = Field(0.0, ge=-60, le=12)
    fade_in: float = Field(0.0, ge=0)
    fade_out: float = Field(0.0, ge=0)

    @field_validator("track")
    @classmethod
    def _track(cls, v):
        if v not in TRACKS:
            raise ValueError("unbekannte Spur")
        return v

    @model_validator(mode="after")
    def _fades(self):
        if self.fade_in + self.fade_out > self.duration + 1e-6:
            raise ValueError("Ein- und Ausblendung sind zusammen länger als der Clip")
        return self


class ProjectData(BaseModel):
    length: float = Field(30, ge=1)
    tracks: dict[str, TrackState] = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list, max_length=MAX_CLIPS)
    script: str = Field("", max_length=5000)  # Sprechtext (KI-Vorschlag oder selbst geschrieben)

    @field_validator("length")
    @classmethod
    def _length(cls, v):
        if v > settings.max_length_s:
            raise ValueError(f"höchstens {settings.max_length_s} Sekunden")
        return v

    @model_validator(mode="after")
    def _complete(self):
        if set(self.tracks) - set(TRACKS):
            raise ValueError("unbekannte Spur")
        self.tracks = {k: self.tracks.get(k, TrackState()) for k in TRACKS}
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError("doppelte Clip-ID")
        return self


def empty_project(length: float = 30) -> dict:
    return ProjectData(length=length).model_dump()


def check_assets(db: Session, user_id: int, data: ProjectData) -> dict[int, Asset]:
    """Alle Clips müssen auf eigene Dateien zeigen und dürfen nicht über deren Ende hinausreichen."""
    ids = {c.asset_id for c in data.clips}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.user_id == user_id, Asset.id.in_(ids))} if ids else {}
    for c in data.clips:
        a = assets.get(c.asset_id)
        if a is None:
            raise ValueError(f"Datei {c.asset_id} nicht gefunden")
        if c.offset + c.duration > a.duration_s + 0.01:
            raise ValueError(f"Clip {c.id} reicht über das Ende von „{a.name}“ hinaus")
    return assets
