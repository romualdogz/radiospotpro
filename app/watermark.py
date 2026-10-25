"""Wasserzeichen der Kunden-Hörprobe: gesprochener Text (KI-Stimme) oder eigene Audiodatei.

Einstellbar unter Admin → Einstellungen. Die eigene Datei liegt unter media/watermark;
Text und Abstand stehen in den allgemeinen Einstellungen (watermark_text, watermark_interval_s).
"""
from pathlib import Path
import uuid

import numpy as np
from sqlalchemy.orm import Session

from . import audio
from .config import settings
from .models import Setting

WM_DIR = settings.media_dir / "watermark"
MAX_BYTES = 5 * 1024 * 1024
MIN_SECONDS, MAX_SECONDS = 0.3, 15.0
VOLUME_DEFAULT, VOLUME_MIN, VOLUME_MAX = 40, 5, 100  # Spitzenpegel des Wasserzeichens in %
MODES = ("text", "file")


def get_config(db: Session) -> dict:
    stored = {s.key: s.value for s in db.query(Setting).filter(
        Setting.key.in_(["watermark_mode", "watermark_file", "watermark_volume"]))}
    name = stored.get("watermark_file", "")
    path = WM_DIR / name if name and Path(name).name == name else None
    if path is not None and not path.is_file():
        path = None
    mode = stored.get("watermark_mode", "text")
    if mode == "file" and path is None:
        mode = "text"  # Datei fehlt → wie bisher den Text sprechen
    return {"mode": mode, "file": path.name if path else "", "path": path,
            "volume": int(stored.get("watermark_volume", VOLUME_DEFAULT))}


def load(cfg: dict) -> np.ndarray | None:
    """Eigene Datei als Mono-Samples – None im Text-Modus."""
    if cfg["mode"] != "file" or cfg["path"] is None:
        return None
    return audio.decode_file(cfg["path"])


def save_file(db: Session, filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in audio.MUSIC_EXTENSIONS:
        raise ValueError("Wasserzeichen: bitte eine MP3-, WAV-, OGG- oder FLAC-Datei hochladen.")
    if len(content) > MAX_BYTES:
        raise ValueError("Wasserzeichen: die Datei ist größer als 5 MB.")
    try:
        samples = audio.decode(content)
    except audio.AudioError as e:
        raise ValueError("Wasserzeichen: die Datei konnte nicht als Audio gelesen werden.") from e
    seconds = len(samples) / audio.SAMPLE_RATE
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise ValueError(f"Wasserzeichen: die Datei ist {seconds:.1f} s lang – erlaubt sind "
                         f"{MIN_SECONDS:g} bis {MAX_SECONDS:g} Sekunden.")
    if not np.abs(samples).max():
        raise ValueError("Wasserzeichen: die Datei ist stumm.")
    old = get_config(db)["path"]
    name = f"wm-{uuid.uuid4().hex[:12]}{ext}"
    WM_DIR.mkdir(parents=True, exist_ok=True)
    (WM_DIR / name).write_bytes(content)
    db.merge(Setting(key="watermark_file", value=name))
    db.commit()
    if old is not None:
        old.unlink(missing_ok=True)
    return name


def remove_file(db: Session) -> None:
    old = get_config(db)["path"]
    db.merge(Setting(key="watermark_file", value=""))
    db.merge(Setting(key="watermark_mode", value="text"))
    db.commit()
    if old is not None:
        old.unlink(missing_ok=True)


def save_options(db: Session, mode: str, volume: int) -> None:
    if mode not in MODES:
        raise ValueError("Wasserzeichen: unbekannte Art")
    if mode == "file" and get_config(db)["path"] is None:
        raise ValueError("Wasserzeichen: bitte zuerst eine Audiodatei hochladen oder „Gesprochener Text“ wählen.")
    db.merge(Setting(key="watermark_mode", value=mode))
    db.merge(Setting(key="watermark_volume", value=str(min(VOLUME_MAX, max(VOLUME_MIN, volume)))))
    db.commit()


def cache_key(cfg: dict, text: str) -> str:
    """Teil des Hörproben-Cache-Schlüssels: ändert sich bei neuer Datei, Art oder Lautstärke."""
    source = cfg["file"] if cfg["mode"] == "file" else text
    return f"{cfg['mode']}:{source}:{cfg['volume']}"
