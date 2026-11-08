"""Lautstärke über die Zeit: Hüllkurven und Ducking.

Beides wird als Kurve mit 100 Werten pro Sekunde berechnet – der Browser (studio.js) verwendet
genau dasselbe Verfahren für das Vorhören, damit Vorhören und Export gleich klingen.
"""
import numpy as np

FPS = 100                 # Kurvenwerte pro Sekunde
DUCK_THRESHOLD_DB = -45   # ab hier gilt die Sprache als „spricht“ (RMS über 10 ms)
DUCK_HOLD_S = 0.25        # in Sprechpausen so lange unten bleiben (kein Pumpen zwischen Wörtern)
DUCK_LOOKAHEAD_S = 0.05   # schon kurz vor dem ersten Wort absenken
DUCK_ATTACK_S = 0.1       # so lange dauert das Absenken (ca. 95 %)


def frames(length_s: float) -> int:
    return int(np.ceil(length_s * FPS)) + 1


def envelope_db(points: list, n: int) -> np.ndarray:
    """Hüllkurve in dB pro Frame: linear zwischen den Punkten, davor/danach konstant."""
    if not points:
        return np.zeros(n, dtype=np.float64)
    t = np.array([p.t for p in points], dtype=np.float64)
    db = np.array([p.db for p in points], dtype=np.float64)
    return np.interp(np.arange(n) / FPS, t, db)


def frame_rms_db(signal: np.ndarray, sr: int, n: int) -> np.ndarray:
    """RMS-Pegel pro 10-ms-Frame (Stereo gemittelt) in dBFS."""
    hop = sr // FPS
    power = (signal.astype(np.float64) ** 2).mean(axis=1) if signal.ndim == 2 else signal.astype(np.float64) ** 2
    m = min(len(power) // hop, n)
    out = np.full(n, -120.0)
    if m:
        out[:m] = 10 * np.log10(np.maximum(power[:m * hop].reshape(m, hop).mean(axis=1), 1e-12))
    return out


def duck_db(voice_db: np.ndarray, amount_db: float, release_s: float) -> np.ndarray:
    """Absenkung in dB pro Frame (0 = keine), geglättet mit Attack/Release."""
    n = len(voice_db)
    active = voice_db > DUCK_THRESHOLD_DB
    hold, ahead = int(DUCK_HOLD_S * FPS), int(DUCK_LOOKAHEAD_S * FPS)
    if active.any():
        idx = np.flatnonzero(active)
        spread = np.zeros(n + 1, dtype=np.int64)  # Intervalle [i - ahead, i + hold] markieren
        np.add.at(spread, np.clip(idx - ahead, 0, n), 1)
        np.add.at(spread, np.clip(idx + hold + 1, 0, n), -1)
        active = np.cumsum(spread[:n]) > 0
    target = np.where(active, -amount_db, 0.0)
    # Zeiten gelten als „fast ganz da“ (3 Zeitkonstanten ≈ 95 %)
    down = np.exp(-3 / (DUCK_ATTACK_S * FPS))
    up = np.exp(-3 / (release_s * FPS))
    out = np.empty(n)
    g = 0.0
    for i in range(n):
        k = down if target[i] < g else up
        g = target[i] + (g - target[i]) * k
        out[i] = g
    return out


def per_sample(curve_db: np.ndarray, n_samples: int, sr: int) -> np.ndarray:
    """Frame-Kurve (dB) → linearer Faktor pro Sample."""
    t = np.arange(n_samples, dtype=np.float64) / sr
    return (10 ** (np.interp(t, np.arange(len(curve_db)) / FPS, curve_db) / 20)).astype(np.float32)
