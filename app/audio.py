"""Hörprobe & Spot: Sprachausgabe über ElevenLabs, Mischen mit Musik, Mastering, Wasserzeichen.

Ablauf:
    1. Text → ElevenLabs (MP3) – Ergebnis wird auf der Platte zwischengespeichert,
       damit gleiche Texte keine Credits doppelt verbrauchen.
    2. Sprache (mono, Mitte), Musik (stereo) und ggf. Wasserzeichen werden in 48 kHz Stereo gemischt.
    3. Mastering auf die Ziel-Lautheit (Standard −8 LUFS, ITU-R BS.1770-4) mit True-Peak-Limiter (−1 dBTP).
    4. Kunden bekommen nur die Hörprobe MIT Wasserzeichen (mono, 32 kHz, klein fürs Web);
       der Admin bekommt den Spot ohne Wasserzeichen (48 kHz, Stereo, 24 Bit) und die Sprache einzeln.

Alles in Python (miniaudio + numpy + scipy), kein ffmpeg nötig.

Konfiguration über Umgebungsvariablen:
    ELEVENLABS_API_KEY   ohne Key ist die KI-Stimme deaktiviert (Browser-Stimme als Ersatz)
    ELEVENLABS_MODEL     Standard: eleven_v4 (Regieanweisungen wie [excited] möglich);
                         Alternativen: eleven_v4_turbo, eleven_v3, eleven_multilingual_v2, eleven_flash_v2_5
    TTS_RATE_LIMIT       max. Hörproben pro Besucher-IP in 10 Minuten (Standard 15)
"""
import hashlib
import io
import json
import os
import re
import time
import wave
from collections import defaultdict, deque
from pathlib import Path

import httpx
import miniaudio
import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import lfilter, resample_poly

from .config import settings

SAMPLE_RATE = 48_000          # Produktions-Samplerate (Spot & Sprache für den Admin)
PREVIEW_RATE = 32_000         # Hörprobe für Kunden (mono, kleinere Datei)
MAX_TEXT_CHARS = 1000
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_v4").strip()

# Was die ElevenLabs-Modelle können (Stand Doku): v4/v3 verstehen Regieanweisungen in [eckigen Klammern],
# kennen aber nur Stability und Similarity – kein Style, kein Speed, keine <break>-Tags.
# Die älteren Modelle (Multilingual v2, Flash, Turbo) sprechen Klammern mit, können dafür Style, Speed und <break>.
_TAG_MODELS = {"eleven_v4", "eleven_v4_turbo", "eleven_v3"}
_TAG = re.compile(r"\[[^\]\n]{1,40}\]")
_BREAK = re.compile(r"<break\s+time=\"[\d.]+s?\"\s*/>")


def supports_audio_tags(model: str | None = None) -> bool:
    return (model or MODEL) in _TAG_MODELS


def prepare_text(text: str, model: str | None = None) -> str:
    """Text an das Modell anpassen: Regieanweisungen bzw. Pausen-Tags nur, wo das Modell sie versteht."""
    if supports_audio_tags(model):
        text = _BREAK.sub(" — ", text)
    else:
        text = _TAG.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def spoken_words(text: str) -> int:
    """Wortanzahl ohne Regieanweisungen und Pausen-Tags."""
    return len(_BREAK.sub(" ", _TAG.sub(" ", text)).split())


def voice_settings(stability: float = 0.5, similarity: float = 0.75, style: float = 0.0,
                   speed: float = 1.0, model: str | None = None) -> dict:
    """Stimm-Einstellungen für ElevenLabs – nur die Werte, die das Modell unterstützt."""
    settings_ = {"stability": round(min(max(stability, 0), 1), 2),
                 "similarity_boost": round(min(max(similarity, 0), 1), 2)}
    if not supports_audio_tags(model):
        settings_["style"] = round(min(max(style, 0), 1), 2)
        settings_["speed"] = round(min(max(speed, 0.7), 1.2), 2)  # erlaubter Bereich bei ElevenLabs
    return settings_

MEDIA_DIR = settings.media_dir
MUSIC_DIR = MEDIA_DIR / "music"
CACHE_DIR = MEDIA_DIR / "cache" / "tts"
MUSIC_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac"}

RATE_LIMIT = int(os.getenv("TTS_RATE_LIMIT", "15"))
RATE_WINDOW = 600
_hits: dict[str, deque] = defaultdict(deque)


class AudioError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def tts_enabled() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY"))


def check_rate_limit(client_id: str) -> None:
    now = time.monotonic()
    hits = _hits[client_id]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        raise AudioError("Zu viele Hörproben – bitte in ein paar Minuten erneut versuchen.", 429)
    hits.append(now)


# --------------------------------------------------------------------------- ElevenLabs

async def synthesize(voice_id: str, text: str, settings_: dict | None = None) -> bytes:
    """Text → MP3 über ElevenLabs, mit Platten-Cache (Schlüssel: Modell, Stimme, Text, Einstellungen)."""
    if not tts_enabled():
        raise AudioError("Die KI-Stimme ist nicht eingerichtet.", 503)
    text = prepare_text(text)
    settings_ = settings_ or voice_settings()
    if not text:
        raise AudioError("Kein Text für die Hörprobe vorhanden.", 422)
    if len(text) > MAX_TEXT_CHARS:
        raise AudioError(f"Der Text ist zu lang für eine Hörprobe (max. {MAX_TEXT_CHARS} Zeichen).", 422)

    key = hashlib.sha256(f"{MODEL}|{voice_id}|{text}|{json.dumps(settings_, sort_keys=True)}".encode()).hexdigest()
    cached = CACHE_DIR / f"{key}.mp3"
    if cached.exists():
        return cached.read_bytes()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                ELEVENLABS_URL.format(voice_id=voice_id),
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "accept": "audio/mpeg"},
                json={"text": text, "model_id": MODEL, "voice_settings": settings_},
            )
    except httpx.HTTPError as e:
        raise AudioError("ElevenLabs ist nicht erreichbar – bitte später erneut versuchen.") from e

    if r.status_code == 401:
        raise AudioError("ElevenLabs-Zugang ist falsch konfiguriert (API-Key).", 503)
    if r.status_code == 404:
        raise AudioError("Diese Stimme wurde bei ElevenLabs nicht gefunden (Voice-ID prüfen).", 503)
    if r.status_code == 429:
        raise AudioError("Die KI-Stimme ist gerade ausgelastet – bitte kurz warten.", 429)
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("detail", {}).get("message", "")
        except (ValueError, AttributeError):
            pass
        raise AudioError(f"Hörprobe konnte nicht erstellt werden. {detail}".strip())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(r.content)
    return r.content


# --------------------------------------------------------------------------- Dekodieren & Kodieren

def decode(data: bytes, channels: int = 1) -> np.ndarray:
    """MP3/WAV/OGG/FLAC (Bytes) → float32 mit SAMPLE_RATE; Form (n,) bei mono, (n, 2) bei stereo."""
    try:
        sound = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16,
                                 nchannels=channels, sample_rate=SAMPLE_RATE)
    except miniaudio.DecodeError as e:
        raise AudioError("Audiodatei konnte nicht gelesen werden.", 422) from e
    samples = np.frombuffer(sound.samples, dtype=np.int16).astype(np.float32) / 32768
    return samples.reshape(-1, 2) if channels == 2 else samples


def decode_file(path: Path, channels: int = 1) -> np.ndarray:
    return decode(path.read_bytes(), channels)


def to_wav(samples: np.ndarray, rate: int = SAMPLE_RATE, bits: int = 16) -> bytes:
    """float32 (n,) oder (n, 2) → WAV mit 16 oder 24 Bit."""
    channels = 1 if samples.ndim == 1 else samples.shape[1]
    x = np.clip(samples, -1, 1).reshape(-1)
    if bits == 24:
        ints = (x * 8_388_607).astype("<i4")
        pcm = ints.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()  # untere 3 Bytes (little endian)
    else:
        pcm = (x * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def preview_wav(samples: np.ndarray) -> bytes:
    """Hörprobe fürs Web: mono, 32 kHz, 16 Bit."""
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    return to_wav(resample_poly(mono, PREVIEW_RATE, SAMPLE_RATE).astype(np.float32), rate=PREVIEW_RATE)


def stereo(x: np.ndarray) -> np.ndarray:
    return x if x.ndim == 2 else np.column_stack([x, x])


# --------------------------------------------------------------------------- Lautheit & Mastering

# K-Filter nach ITU-R BS.1770-4 für 48 kHz (Shelving + Hochpass)
_K_SHELF = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
_K_HIGHPASS = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])


def loudness(x: np.ndarray) -> float:
    """Integrierte Lautheit in LUFS (ITU-R BS.1770-4, Gating −70 LUFS absolut / −10 LU relativ)."""
    x = stereo(x).astype(np.float32, copy=False)
    y = lfilter(*_K_HIGHPASS, lfilter(*_K_SHELF, x, axis=0), axis=0).astype(np.float64)
    block, step = int(0.4 * SAMPLE_RATE), int(0.1 * SAMPLE_RATE)
    if len(y) < block:
        return -70.0
    power = np.cumsum(np.concatenate([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    starts = np.arange(0, len(y) - block + 1, step)
    z = ((power[starts + block] - power[starts]) / block).sum(axis=1)  # Kanalgewichte L/R = 1
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    z = z[lk > -70]
    if not len(z):
        return -70.0
    relative = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[-0.691 + 10 * np.log10(z) > relative]
    return float(-0.691 + 10 * np.log10(z.mean()))


def true_peak_db(x: np.ndarray) -> float:
    """True Peak (4-fach überabgetastet) in dBTP.

    Zwischen-Sample-Spitzen liegen höchstens wenige dB über den Sample-Spitzen – daher werden nur
    Abschnitte überabgetastet, deren Pegel bis 6 dB an das Maximum heranreicht (deutlich schneller).
    """
    x = stereo(x)
    block, pad = 4096, 64
    peaks = np.abs(x).max(axis=1)
    sample_peak = float(peaks.max())
    if sample_peak <= 0:
        return -180.0
    n_blocks = -(-len(x) // block)
    block_peaks = np.pad(peaks, (0, n_blocks * block - len(x))).reshape(n_blocks, block).max(axis=1)
    peak = sample_peak
    for b in np.flatnonzero(block_peaks >= sample_peak / 2):
        start, end = max(b * block - pad, 0), min((b + 1) * block + pad, len(x))
        peak = max(peak, float(np.abs(resample_poly(x[start:end], 4, 1, axis=0)).max()))
    return 20 * np.log10(peak)


def compress(x: np.ndarray, threshold_db: float = -18.0, ratio: float = 3.0) -> np.ndarray:
    """Sanfter RMS-Kompressor (Stereo verlinkt) vor dem Limiter – macht hohe Lautheit weniger hart."""
    sr = SAMPLE_RATE
    ms = uniform_filter1d((x ** 2).mean(axis=1), size=int(0.03 * sr))         # 30 ms RMS-Fenster
    level = 10 * np.log10(np.maximum(ms, 1e-12))
    reduction = np.minimum(0, (threshold_db - level) * (1 - 1 / ratio))
    reduction = uniform_filter1d(reduction, size=int(0.08 * sr))               # 80 ms Glättung
    return x * (10 ** (reduction / 20))[:, None]


def limit(x: np.ndarray, ceiling_db: float) -> np.ndarray:
    """Brickwall-Limiter (Stereo verlinkt): 3 ms Hold/Lookahead, 1,5 ms Glättung."""
    x = stereo(x)
    ceiling = 10 ** (ceiling_db / 20)
    peak = np.abs(x).max(axis=1)
    gain = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    hold = int(0.003 * SAMPLE_RATE)
    smooth = int(0.0015 * SAMPLE_RATE) | 1
    # Minimum über ±Hold, danach Glättung über ein kürzeres Fenster: die Verstärkung an jeder
    # Spitze bleibt dadurch garantiert unter dem nötigen Wert (kein Überschwingen).
    gain = uniform_filter1d(minimum_filter1d(gain, size=2 * hold + 1), size=smooth)
    return x * gain[:, None]


def master(x: np.ndarray, target_lufs: float = -8.0, ceiling_dbtp: float = -1.0) -> np.ndarray:
    """Kompressor → Verstärkung → Limiter, bis die Ziel-Lautheit (±0,1 LU) erreicht ist.

    Die nötige Verstärkung wird per Sekantenverfahren gesucht (meist 3–4 Durchläufe).
    """
    x = stereo(x)
    if loudness(x) <= -70:
        return x
    x = compress(x)
    sample_ceiling = ceiling_dbtp - 1.0  # Reserve für Spitzen zwischen den Samples (True Peak)

    def attempt(gain_db):
        y = limit(x * 10 ** (gain_db / 20), sample_ceiling)
        return y, loudness(y) - target_lufs

    g0 = target_lufs - loudness(x)
    y, e0 = attempt(g0)
    g1 = g0 - e0  # Limiter kostet Lautheit → entsprechend mehr Verstärkung
    for _ in range(8):
        if abs(e0) < 0.1:
            break
        y, e1 = attempt(g1)
        if abs(e1) < 0.1:
            break
        slope = (e1 - e0) / (g1 - g0) if g1 != g0 else 1.0
        g0, e0 = g1, e1
        g1 = g1 - e1 / max(slope, 0.05)  # Steigung > 0: mehr Verstärkung → lauter
    tp = true_peak_db(y)
    if tp > ceiling_dbtp:  # selten: nachregeln, falls Zwischenwerte doch über der Grenze liegen
        y = limit(y, sample_ceiling - (tp - ceiling_dbtp))
    return y


def normalize_true_peak(x: np.ndarray, peak_dbtp: float = -1.0) -> np.ndarray:
    """Pegel so setzen, dass der True Peak genau bei peak_dbtp liegt (ohne Kompression)."""
    if not np.abs(x).max():
        return x
    return x * 10 ** ((peak_dbtp - true_peak_db(x)) / 20)


# --------------------------------------------------------------------------- Mischen

def _ramp(n: int, start: float, end: float) -> np.ndarray:
    return np.linspace(start, end, max(n, 1), dtype=np.float32)[:n]


def beep(seconds: float = 0.25, freq: float = 1000) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    env = np.minimum(1, np.minimum(t, seconds - t) * 40)
    return (np.sin(2 * np.pi * freq * t) * env * 0.6).astype(np.float32)


def mix(voice: np.ndarray, music: np.ndarray | None = None, watermark: np.ndarray | None = None,
        watermark_every: float = 7.0, watermark_level: float = 0.4,
        bed_level: float = 0.14, open_level: float = 0.45, music_gain: float = 1.0) -> np.ndarray:
    """Sprache (mono, Mitte) über Musikbett (stereo) legen und optional Wasserzeichen einstreuen.

    Musik: 1,5 s Intro, unter der Stimme abgesenkt (open_level → bed_level, Standard 45 % → 14 %),
    2,5 s Outro, Fade-in/-out. music_gain: Lautstärke-Korrektur des einzelnen Musikstücks.
    Ergebnis: Stereo (n, 2) mit SAMPLE_RATE, noch nicht gemastert.
    """
    sr = SAMPLE_RATE
    voice = voice / max(float(np.abs(voice).max()), 1e-6) * 0.9

    if music is not None and len(music):
        music = stereo(music)
        intro, outro, ramp = int(1.5 * sr), int(2.5 * sr), int(0.3 * sr)
        total = intro + len(voice) + outro
        reps = -(-total // len(music))
        bed = np.tile(music, (reps, 1))[:total] / max(float(np.abs(music).max()), 1e-6) * music_gain
        gain = np.full(total, open_level, dtype=np.float32)
        v0, v1 = intro, intro + len(voice)
        gain[v0:v1] = bed_level
        gain[max(v0 - ramp, 0):v0] = _ramp(min(ramp, v0), open_level, bed_level)
        gain[v1:v1 + ramp] = _ramp(min(ramp, total - v1), bed_level, open_level)
        gain[: int(0.5 * sr)] *= _ramp(int(0.5 * sr), 0, 1)               # Fade-in
        fade = int(1.5 * sr)
        gain[-fade:] *= _ramp(fade, 1, 0)                                    # Fade-out
        out = (bed * gain[:, None]).astype(np.float32)
        out[v0:v1] += voice[:, None]
    else:
        pad = int(0.3 * sr)
        out = stereo(np.concatenate([np.zeros(pad, np.float32), voice, np.zeros(pad, np.float32)])).copy()

    if watermark is not None and len(watermark):
        wm = watermark / max(float(np.abs(watermark).max()), 1e-6) * watermark_level
        # erstes Wasserzeichen nach 2 s – bei sehr kurzen Hörproben mittig, damit keine ungeschützt bleibt
        pos = min(int(2.0 * sr), max(0, (len(out) - len(wm)) // 2))
        step = max(int(watermark_every * sr), len(wm) + sr)
        while pos < len(out):
            end = min(pos + len(wm), len(out))
            out[pos:end] += wm[: end - pos, None]
            pos += step

    return out
