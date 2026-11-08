"""Mehrspur-Mischung → fertiger Spot (WAV, 48 kHz, Stereo, 24 Bit).

Läuft nie im Webprozess: der Worker startet je Auftrag `python -m studio.render <export_id>`
als eigenen Prozess mit Zeitlimit.
"""
import secrets
import sys
import traceback

import numpy as np

from app import audio

from .models import Export, StudioUser, now
from .projects import ProjectData, resolve_sources

SR = audio.SAMPLE_RATE
PEAK_CEILING = -1.0  # dBTP


def _db(x: float) -> float:
    return 10 ** (x / 20)


LOOP_XFADE = 0.05  # s – Überblendung an der Nahtstelle eines Loops (gegen Klicks)


def fade_curve(x: np.ndarray, curve: str) -> np.ndarray:
    """0 → 1 entlang x ∈ [0, 1]. „smooth“ = S-Kurve (Kosinus), muss mit dem Browser übereinstimmen."""
    return x if curve == "linear" else (0.5 - 0.5 * np.cos(np.pi * x)).astype(np.float32)


def _envelope(n: int, gain: float, fade_in: int, fade_out: int, curve: str = "linear") -> np.ndarray:
    env = np.full(n, gain, dtype=np.float32)
    if fade_in:
        env[:fade_in] *= fade_curve(np.linspace(0, 1, fade_in, endpoint=False, dtype=np.float32), curve)
    if fade_out:
        env[n - fade_out:] *= fade_curve(np.linspace(1, 0, fade_out, dtype=np.float32), curve)
    return env


def looped(src: np.ndarray, offset: int, n: int) -> np.ndarray:
    """`n` Samples ab `offset`, die Datei wird dabei wiederholt (Nahtstellen mit gleichlauter Überblendung)."""
    length = len(src)
    xf = min(int(LOOP_XFADE * SR), length // 4)
    if offset + n <= length or xf == 0:
        reps = -(-(offset + n) // max(length, 1))
        return np.tile(src, (reps, 1))[offset:offset + n] if offset + n > length else src[offset:offset + n]
    period = length - xf
    total = offset + n
    out = np.zeros((total + length, src.shape[1]), dtype=np.float32)
    t = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
    fade_in, fade_out = np.sin(t * np.pi / 2), np.cos(t * np.pi / 2)
    pos, first = 0, True
    while pos < total:
        piece = src.copy()
        if not first:
            piece[:xf] *= fade_in
        piece[-xf:] *= fade_out
        out[pos:pos + length] += piece
        pos += period
        first = False
    return out[offset:total]


def mix_project(data: ProjectData, files: dict) -> np.ndarray:
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
        key = clip.source
        if key not in cache:
            path = files[key]
            cache[key] = audio.stereo(audio.decode_file(getattr(path, "path", path), channels=2))
        src = cache[key]
        a = int(round(clip.offset * SR))
        want = min(int(round(clip.duration * SR)), total - start)
        piece = looped(src, a, want) if clip.loop else src[a:a + want]
        n = len(piece)
        if not n:
            continue
        full = int(round(clip.duration * SR))  # Fade-out bezieht sich auf das Clip-Ende, auch wenn es abgeschnitten ist
        env = _envelope(full, _db(clip.gain_db + track.gain_db),
                        min(int(clip.fade_in * SR), full), min(int(clip.fade_out * SR), full), clip.fade_curve)[:n]
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
            owner = db.get(StudioUser, job.user_id)
            if owner is None:
                raise RuntimeError("Konto nicht gefunden.")
            try:
                sources = resolve_sources(db, owner, data)
            except ValueError as e:
                raise RuntimeError("Eine verwendete Datei wurde inzwischen gelöscht.") from e
            result = finish(mix_project(data, sources), job.loudness)
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
