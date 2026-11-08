"""Dateien pro Nutzer: Uploads (mit Wellenform-Vorschau) und Exporte, Kontingent."""
import json
import secrets
from pathlib import Path

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audio  # gemeinsamer Audio-Kern (Dekodieren, Lautheit, Mastering)

from .config import settings
from .models import Asset, Export, StudioUser

EXTENSIONS = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg"}
PEAKS_PER_SECOND = 50


class StorageError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def user_dir(user_id: int, kind: str) -> Path:
    path = settings.media_dir / "users" / str(user_id) / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(asset: Asset) -> Path:
    return user_dir(asset.user_id, "assets") / asset.stored_name


def peaks_path(asset: Asset) -> Path:
    return asset_path(asset).with_suffix(".peaks.json")


def export_path(export: Export) -> Path:
    return user_dir(export.user_id, "exports") / export.stored_name


def used_bytes(db: Session, user_id: int) -> int:
    a = db.query(func.coalesce(func.sum(Asset.size_bytes), 0)).filter(Asset.user_id == user_id).scalar()
    e = (db.query(func.coalesce(func.sum(Export.size_bytes), 0))
         .filter(Export.user_id == user_id, Export.status == "done").scalar())
    return int(a) + int(e)


def quota_bytes(user: StudioUser) -> int:
    return user.quota_mb * 1024 * 1024


def check_quota(db: Session, user: StudioUser, extra: int) -> None:
    if used_bytes(db, user.id) + extra > quota_bytes(user):
        raise StorageError(f"Speicherplatz voll ({user.quota_mb} MB). Bitte alte Dateien oder Exporte löschen.", 413)


def compute_peaks(samples: np.ndarray) -> list[int]:
    """Spitzenwerte (0–255) mit 50 Werten pro Sekunde für die Wellenform im Browser."""
    mono = np.abs(samples).max(axis=1) if samples.ndim == 2 else np.abs(samples)
    hop = audio.SAMPLE_RATE // PEAKS_PER_SECOND
    n = -(-len(mono) // hop)
    padded = np.pad(mono, (0, n * hop - len(mono))).reshape(n, hop).max(axis=1)
    return np.clip(np.round(padded * 255), 0, 255).astype(int).tolist()


def check_upload_name(filename: str) -> tuple[str, str]:
    name = Path(filename or "upload").name[:200] or "upload"
    ext = Path(name).suffix.lower()
    if ext not in EXTENSIONS:
        raise StorageError("Bitte WAV, MP3, FLAC oder OGG hochladen.", 415)
    return name, ext


def save_upload(db: Session, user: StudioUser, filename: str, tmp: Path, origin: str = "upload") -> Asset:
    """Zwischengespeicherte Datei prüfen (Kontingent, Audio, Länge), Wellenform berechnen, übernehmen.
    Die Datei `tmp` wird in jedem Fall verschoben oder gelöscht."""
    name, ext = check_upload_name(filename)
    path = user_dir(user.id, "assets") / (secrets.token_hex(12) + ext)
    try:
        size = tmp.stat().st_size
        if size == 0:
            raise StorageError("Die Datei ist leer.")
        check_quota(db, user, size)
        tmp.replace(path)
        try:
            samples = audio.decode_file(path, channels=2)
        except audio.AudioError as e:
            raise StorageError("Die Datei konnte nicht als Audio gelesen werden.", 422) from e
        duration = len(samples) / audio.SAMPLE_RATE
        if duration < 0.01:
            raise StorageError("Die Datei enthält kein Audio.", 422)
        if duration > settings.max_asset_minutes * 60:
            raise StorageError(f"Die Datei ist länger als {settings.max_asset_minutes:g} Minuten.", 413)
        asset = Asset(user_id=user.id, name=name, stored_name=path.name, media_type=EXTENSIONS[ext],
                      size_bytes=size, duration_s=round(duration, 4), origin=origin)
        peaks_path(asset).write_text(json.dumps(compute_peaks(samples), separators=(",", ":")))
    except BaseException:
        tmp.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        path.with_suffix(".peaks.json").unlink(missing_ok=True)
        raise
    db.add(asset)
    db.commit()
    return asset


def temp_upload_path(user_id: int) -> Path:
    return user_dir(user_id, "tmp") / (secrets.token_hex(12) + ".part")


def delete_asset(db: Session, asset: Asset) -> None:
    asset_path(asset).unlink(missing_ok=True)
    peaks_path(asset).unlink(missing_ok=True)
    db.delete(asset)
    db.commit()


def delete_export_file(export: Export) -> None:
    if export.stored_name:
        export_path(export).unlink(missing_ok=True)
