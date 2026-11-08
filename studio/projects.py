"""Projektformat (gemeinsam für Speichern, Vorhören im Browser und Rendern) und Prüfung."""
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .config import settings
from .models import TRACKS, Asset, Library, LibraryItem, StudioUser

MAX_CLIPS = 300


MAX_ENVELOPE_POINTS = 200


class EnvPoint(BaseModel):
    t: float = Field(ge=0)                    # Zeit auf der Zeitleiste (s)
    db: float = Field(0.0, ge=-60, le=12)     # Lautstärke relativ zur Spur (dB)


class TrackState(BaseModel):
    gain_db: float = Field(0.0, ge=-60, le=12)
    mute: bool = False
    solo: bool = False
    # Lautstärke über die Zeit; leer = konstant
    envelope: list[EnvPoint] = Field(default_factory=list, max_length=MAX_ENVELOPE_POINTS)
    duck: bool = False                        # leiser, sobald die Sprache spricht

    @field_validator("envelope")
    @classmethod
    def _sorted(cls, v):
        return sorted(v, key=lambda p: p.t)


class Ducking(BaseModel):
    amount_db: float = Field(10.0, ge=0, le=30)   # um so viel dB absenken
    release_s: float = Field(0.5, ge=0.1, le=3)   # so schnell wieder hochfahren


FADE_CURVES = ("linear", "smooth")


class Clip(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    asset_id: int | None = None   # eigene Datei …
    lib_id: int | None = None     # … oder Datei aus einer Bibliothek
    track: str
    start: float = Field(ge=0)        # Position auf der Zeitleiste (s)
    offset: float = Field(0.0, ge=0)  # Beginn innerhalb der Datei (s)
    duration: float = Field(gt=0)     # hörbare Länge (s)
    gain_db: float = Field(0.0, ge=-60, le=12)
    fade_in: float = Field(0.0, ge=0)
    fade_out: float = Field(0.0, ge=0)
    fade_curve: str = "linear"    # linear | smooth (S-Kurve); neue Clips im Editor: smooth
    loop: bool = False            # Datei wiederholen, solange der Clip dauert (z. B. Atmo)

    @property
    def source(self) -> tuple[str, int]:
        return ("a", self.asset_id) if self.asset_id is not None else ("l", self.lib_id)

    @field_validator("fade_curve")
    @classmethod
    def _curve(cls, v):
        if v not in FADE_CURVES:
            raise ValueError("unbekannte Fade-Kurve")
        return v

    @field_validator("track")
    @classmethod
    def _track(cls, v):
        if v not in TRACKS:
            raise ValueError("unbekannte Spur")
        return v

    @model_validator(mode="after")
    def _fades(self):
        if (self.asset_id is None) == (self.lib_id is None):
            raise ValueError("Clip braucht genau eine Quelle (eigene Datei oder Bibliothek)")
        if self.fade_in + self.fade_out > self.duration + 1e-6:
            raise ValueError("Ein- und Ausblendung sind zusammen länger als der Clip")
        return self


class ProjectData(BaseModel):
    length: float = Field(30, ge=1)
    tracks: dict[str, TrackState] = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list, max_length=MAX_CLIPS)
    script: str = Field("", max_length=5000)  # Sprechtext (KI-Vorschlag oder selbst geschrieben)
    ducking: Ducking = Field(default_factory=Ducking)

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
    data = ProjectData(length=length)
    for k in ("music", "atmo"):  # neue Projekte: Musik und Atmo weichen der Stimme aus
        data.tracks[k].duck = True
    return data.model_dump()


class Source(NamedTuple):
    path: Path
    duration: float
    name: str


def accessible_libraries(db: Session, user: StudioUser) -> list[int]:
    """IDs der Bibliotheken, die das Konto nutzen darf (Admins: alle)."""
    q = db.query(Library.id)
    if user.role != "admin":
        allowed = [i for i in (user.libraries or []) if isinstance(i, int)]
        q = q.filter(or_(Library.for_all.is_(True), Library.id.in_(allowed)))
    return [i for (i,) in q]


def resolve_sources(db: Session, user: StudioUser, data: ProjectData) -> dict[tuple[str, int], Source]:
    """Alle Clips müssen auf eigene Dateien oder erlaubte Bibliotheksdateien zeigen und dürfen
    (ohne Loop) nicht über deren Ende hinausreichen."""
    from . import storage
    keys = {c.source for c in data.clips}
    out: dict[tuple[str, int], Source] = {}
    asset_ids = [i for k, i in keys if k == "a"]
    if asset_ids:
        for a in db.query(Asset).filter(Asset.user_id == user.id, Asset.id.in_(asset_ids)):
            out[("a", a.id)] = Source(storage.asset_path(a), a.duration_s, a.name)
    lib_ids = [i for k, i in keys if k == "l"]
    if lib_ids:
        allowed = accessible_libraries(db, user)
        for it in db.query(LibraryItem).filter(LibraryItem.id.in_(lib_ids), LibraryItem.library_id.in_(allowed)):
            out[("l", it.id)] = Source(storage.library_path(it), it.duration_s, it.name)
    for c in data.clips:
        src = out.get(c.source)
        if src is None:
            raise ValueError(f"Datei {'aus der Bibliothek ' if c.lib_id else ''}{c.asset_id or c.lib_id} nicht gefunden")
        if c.offset >= src.duration:
            raise ValueError(f"Clip {c.id} beginnt hinter dem Ende von „{src.name}“")
        if not c.loop and c.offset + c.duration > src.duration + 0.01:
            raise ValueError(f"Clip {c.id} reicht über das Ende von „{src.name}“ hinaus")
    return out
