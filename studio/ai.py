"""KI im Studio: Textvorschläge (Claude) und Sprachaufnahmen (ElevenLabs).

Nutzt dieselben Funktionen wie der Konfigurator (app/ai.py, app/audio.py) und dieselben API-Keys.
Nur Stimmen, die der Admin freigibt, sind wählbar. Verbrauch wird pro Konto und Monat gezählt.
"""
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import ai as text_ai
from app import audio

from .models import AiUsage, StudioUser, StudioVoice

RATE_WINDOW = 600
RATE = {"script": 10, "voice": 20}  # Anfragen pro Konto in 10 Minuten
_hits: dict[tuple[int, str], deque] = defaultdict(deque)
MAX_CHARS = audio.MAX_TEXT_CHARS


class AiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def text_enabled() -> bool:
    return text_ai.is_enabled()


def voice_enabled() -> bool:
    return audio.tts_enabled()


def tags_supported() -> bool:
    return audio.supports_audio_tags()


def _rate(user_id: int, kind: str) -> None:
    now = time.monotonic()
    hits = _hits[(user_id, kind)]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE[kind]:
        raise AiError("Zu viele Anfragen in kurzer Zeit – bitte ein paar Minuten warten.", 429)
    hits.append(now)


def month_start() -> datetime:
    n = datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(db: Session, user_id: int) -> dict:
    rows = (db.query(AiUsage.kind, func.count(AiUsage.id), func.coalesce(func.sum(AiUsage.chars), 0))
            .filter(AiUsage.user_id == user_id, AiUsage.created_at >= month_start()).group_by(AiUsage.kind).all())
    by = {k: (n, c) for k, n, c in rows}
    return {"scripts": by.get("script", (0, 0))[0], "voice_chars": int(by.get("voice", (0, 0))[1])}


def _record(db: Session, user: StudioUser, kind: str, chars: int) -> None:
    db.add(AiUsage(user_id=user.id, kind=kind, chars=chars))
    db.commit()


# --------------------------------------------------------------------------- Text

TONALITIES = ["freundlich", "energisch", "humorvoll", "seriös", "emotional", "jugendlich", "edel"]


async def scripts(db: Session, user: StudioUser, *, occasion: str, seconds: int, tonality: str, firma: str,
                  botschaft: str, cta: str, audio_tags: bool) -> list[str]:
    if not text_enabled():
        raise AiError("Der KI-Text ist nicht eingerichtet (ANTHROPIC_API_KEY fehlt).", 503)
    if user.scripts_month is not None and usage(db, user.id)["scripts"] >= user.scripts_month:
        raise AiError(f"Monatskontingent für KI-Texte ausgeschöpft ({user.scripts_month}).", 403)
    _rate(user.id, "script")
    try:
        result = await text_ai.generate_scripts(
            count=3, occasion=occasion, seconds=seconds, tonality=tonality, firma=firma, botschaft=botschaft,
            cta=cta, audio_tags=audio_tags and tags_supported(),
            style_instruction="Schreibe in natürlichem, gut sprechbarem Deutsch für Profi-Sprecher.")
    except text_ai.ScriptError as e:
        raise AiError(str(e), e.status) from e
    _record(db, user, "script", 0)
    return result


# --------------------------------------------------------------------------- Stimme

def spoken_chars(text: str) -> int:
    return len(audio.prepare_text(text))


def voice_settings(v: StudioVoice) -> dict:
    return audio.voice_settings(v.stability, v.similarity, v.style, v.speed)


async def speak(db: Session, user: StudioUser, voice: StudioVoice, text: str) -> bytes:
    if not voice_enabled():
        raise AiError("Die KI-Stimme ist nicht eingerichtet (ELEVENLABS_API_KEY fehlt).", 503)
    chars = spoken_chars(text)
    if not chars:
        raise AiError("Bitte zuerst einen Text eingeben.", 422)
    if chars > MAX_CHARS:
        raise AiError(f"Der Text ist zu lang (max. {MAX_CHARS} Zeichen pro Aufnahme) – bitte aufteilen.", 422)
    if user.tts_chars_month is not None and usage(db, user.id)["voice_chars"] + chars > user.tts_chars_month:
        raise AiError(f"Monatskontingent für die KI-Stimme reicht nicht ({user.tts_chars_month} Zeichen).", 403)
    _rate(user.id, "voice")
    try:
        data = await audio.synthesize(voice.elevenlabs_voice_id, text, voice_settings(voice))
    except audio.AudioError as e:
        raise AiError(str(e), e.status) from e
    _record(db, user, "voice", chars)
    return data


def asset_name(voice: StudioVoice, text: str) -> str:
    words = " ".join(audio.prepare_text(re.sub(r"\[[^\]]*\]", " ", text)).split()[:5])
    return f"{voice.name} – {words}"[:190] + ".mp3"  # „KI“-Kennzeichen zeigt die Dateiliste


# --------------------------------------------------------------------------- Stimmen aus dem ElevenLabs-Konto (Admin)

_account_cache: tuple[float, list[dict]] | None = None


def account_voices(force: bool = False) -> list[dict]:
    """Stimmen im ElevenLabs-Konto – nur zur Auswahl im Admin, 5 Minuten zwischengespeichert."""
    global _account_cache
    if not voice_enabled():
        return []
    if _account_cache and not force and time.monotonic() - _account_cache[0] < 300:
        return _account_cache[1]
    try:
        r = httpx.get("https://api.elevenlabs.io/v1/voices", timeout=15,
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]})
        r.raise_for_status()
        voices = [{"id": v["voice_id"], "name": v.get("name", v["voice_id"]),
                   "info": ", ".join(str(x) for x in (v.get("labels") or {}).values() if x)}
                  for v in r.json().get("voices", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return []
    _account_cache = (time.monotonic(), sorted(voices, key=lambda v: v["name"].lower()))
    return _account_cache[1]

