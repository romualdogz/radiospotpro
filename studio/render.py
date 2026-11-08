"""Mehrspur-Mischung → fertiger Spot (WAV, 48 kHz, Stereo, 24 Bit).

Läuft nie im Webprozess: der Worker startet je Auftrag `python -m studio.render <export_id>`
als eigenen Prozess mit Zeitlimit.
"""
import secrets
import sys
import traceback

import numpy as np

from app import audio

from . import automation
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


def _clip_into(buf: np.ndarray, clip, src: np.ndarray) -> None:
    """Clip (mit Clip-Lautstärke, Fades, Loop) in den Spurpuffer legen."""
    total = len(buf)
    start = int(round(clip.start * SR))
    if start >= total:
        return
    a = int(round(clip.offset * SR))
    want = min(int(round(clip.duration * SR)), total - start)
    piece = looped(src, a, want) if clip.loop else src[a:a + want]
    n = len(piece)
    if not n:
        return
    full = int(round(clip.duration * SR))  # Fade-out bezieht sich auf das Clip-Ende, auch wenn es abgeschnitten ist
    env = _envelope(full, _db(clip.gain_db), min(int(clip.fade_in * SR), full),
                    min(int(clip.fade_out * SR), full), clip.fade_curve)[:n]
    buf[start:start + n] += piece * env[:, None]


def mix_project(data: ProjectData, files: dict) -> np.ndarray:
    """Spuren einzeln mischen: Clips → Spurlautstärke × Hüllkurve (× Ducking) → Summe.
    Die Sprach-Spur wird zuerst gemischt, ihr Pegel steuert das Ducking der anderen Spuren."""
    total = int(round(data.length * SR))
    n_frames = automation.frames(data.length)
    out = np.zeros((total, 2), dtype=np.float32)
    soloed = {k for k, t in data.tracks.items() if t.solo}
    cache: dict = {}

    def source(clip):
        key = clip.source
        if key not in cache:
            path = files[key]
            cache[key] = audio.stereo(audio.decode_file(getattr(path, "path", path), channels=2))
        return cache[key]

    duck = None
    for name in ["voice"] + [k for k in data.tracks if k != "voice"]:
        track = data.tracks[name]
        clips = [c for c in data.clips if c.track == name]
        audible = not (track.mute or (soloed and name not in soloed))
        if not clips or (not audible and name != "voice"):
            continue
        buf = np.zeros((total, 2), dtype=np.float32)
        for clip in clips:
            _clip_into(buf, clip, source(clip))
        curve = track.gain_db + automation.envelope_db(track.envelope, n_frames)
        if name != "voice" and track.duck and duck is not None:
            curve = curve + duck
        buf *= automation.per_sample(curve, total, SR)[:, None]
        if name == "voice":
            if audible:
                duck = automation.duck_db(automation.frame_rms_db(buf, SR, n_frames),
                                          data.ducking.amount_db, data.ducking.release_s)
                out += buf
            continue
        out += buf
    return out


def normalize(mix: np.ndarray, target: float) -> np.ndarray:
    """Loudness-Normalisierung (z. B. EBU R128): nur Verstärkung, Dynamik bleibt. Spitzen über −1 dBTP
    fängt der Limiter ab; kostet das Lautheit, wird einmal nachverstärkt."""
    current = audio.loudness(mix)
    if current <= -70:
        return mix
    out = mix * 10 ** ((target - current) / 20)
    for _ in range(3):
        if audio.true_peak_db(out) <= PEAK_CEILING:
            break
        out = audio.limit(out, PEAK_CEILING - 1.0)
        miss = target - audio.loudness(out)
        if abs(miss) < 0.1:
            break
        out = out * 10 ** (miss / 20)
    return out


def finish(mix: np.ndarray, loudness: float | None, mode: str = "master") -> np.ndarray:
    """Ziel-Lautheit per Mastering (Kompressor + Limiter, laut, wie im Konfigurator) oder Normalisierung
    (nur Verstärkung). Ohne Ziel: Pegel bleibt, nur Spitzen über −1 dBTP werden begrenzt."""
    if not np.abs(mix).max():
        return mix
    if loudness is not None and mode == "normalize":
        out = normalize(mix, loudness)
    elif loudness is not None:
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
            result = finish(mix_project(data, sources), job.loudness, job.mode)
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
