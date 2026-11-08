"""Mehrspur-Mischung → fertiger Spot (WAV, 48 kHz, Stereo, 24 Bit).

Läuft nie im Webprozess: der Worker startet je Auftrag `python -m studio.render <export_id>`
als eigenen Prozess mit Zeitlimit.
"""
import secrets
import sys
import traceback
from pathlib import Path

import numpy as np

from app import audio

from .models import TRACKS, Asset, Export, now
from .projects import ProjectData

SR = audio.SAMPLE_RATE
PEAK_CEILING = -1.0  # dBTP


def _db(x: float) -> float:
    return 10 ** (x / 20)


def _envelope(n: int, gain: float, fade_in: int, fade_out: int) -> np.ndarray:
    env = np.full(n, gain, dtype=np.float32)
    if fade_in:
        env[:fade_in] *= np.linspace(0, 1, fade_in, endpoint=False, dtype=np.float32)
    if fade_out:
        env[n - fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)
    return env


def mix_project(data: ProjectData, files: dict[int, Path]) -> np.ndarray:
    """Clips platzieren, Clip- und Spurlautstärke, Fades, Mute/Solo anwenden → Stereo-Mix (float32)."""
    total = int(round(data.length * SR))
    out = np.zeros((total, 2), dtype=np.float32)
    soloed = {k for k, t in data.tracks.items() if t.solo}
    cache: dict[int, np.ndarray] = {}
    for clip in data.clips:
        track = data.tracks[clip.track]
        if track.mute or (soloed and clip.track not in soloed):
            continue
        start = int(round(clip.start * SR))
        if start >= total:
            continue
        if clip.asset_id not in cache:
            cache[clip.asset_id] = audio.stereo(audio.decode_file(files[clip.asset_id], channels=2))
        src = cache[clip.asset_id]
        a = int(round(clip.offset * SR))
        piece = src[a:a + int(round(clip.duration * SR))]
        n = len(piece)
        if not n:
            continue
        env = _envelope(n, _db(clip.gain_db + track.gain_db),
                        min(int(clip.fade_in * SR), n), min(int(clip.fade_out * SR), n))
        end = min(start + n, total)
        out[start:end] += piece[:end - start] * env[:end - start, None]
    return out


def finish(mix: np.ndarray, loudness: float | None) -> np.ndarray:
    """Mit Ziel-Lautheit: Mastering wie im Konfigurator. Ohne: Pegel bleibt, nur Spitzen über −1 dBTP werden begrenzt."""
    if not np.abs(mix).max():
        return mix
    if loudness is not None:
        out = audio.master(mix, target_lufs=loudness, ceiling_dbtp=PEAK_CEILING)
    elif audio.true_peak_db(mix) > PEAK_CEILING:
        out = audio.limit(mix, PEAK_CEILING - 1.0)
    else:
        return mix
    # Garantie für die Abgabe: True Peak nie über −1 dBTP (der Limiter kann bei extremem Material
    # knapp darüber landen) – dann den ganzen Spot minimal leiser machen.
    for _ in range(3):
        tp = audio.true_peak_db(out)
        if tp <= PEAK_CEILING:
            break
        out = out * 10 ** ((PEAK_CEILING - 0.05 - tp) / 20)
    return out


def run(export_id: int) -> int:
    from . import storage
    from .database import SessionLocal

    with SessionLocal() as db:
        job = db.get(Export, export_id)
        if job is None or job.status != "running":
            return 1
        try:
            data = ProjectData.model_validate(job.snapshot)
            ids = {c.asset_id for c in data.clips}
            assets = {a.id: a for a in db.query(Asset).filter(Asset.user_id == job.user_id, Asset.id.in_(ids))} if ids else {}
            missing = ids - set(assets)
            if missing:
                raise RuntimeError("Eine verwendete Datei wurde inzwischen gelöscht.")
            result = finish(mix_project(data, {i: storage.asset_path(a) for i, a in assets.items()}), job.loudness)
            job.stored_name = secrets.token_hex(12) + ".wav"
            path = storage.export_path(job)
            path.write_bytes(audio.to_wav(result, bits=24))
            job.size_bytes = path.stat().st_size
            job.measured_lufs = round(audio.loudness(result), 1)
            job.measured_peak = round(audio.true_peak_db(result), 1) if np.abs(result).max() else None
            job.status = "done"
        except Exception as e:  # noqa: BLE001 – Fehler landet beim Nutzer, Details im Log
            traceback.print_exc()
            job.status, job.error = "failed", (str(e) if isinstance(e, (RuntimeError, ValueError)) else "Rendern fehlgeschlagen.")[:500]
        job.finished_at = now()
        db.commit()
        return 0 if job.status == "done" else 1


if __name__ == "__main__":
    sys.exit(run(int(sys.argv[1])))
