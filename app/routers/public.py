"""Öffentliche API, die der Konfigurator (Frontend) verwendet."""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import ai, audio, branding, music_mix, pdf, theme, watermark as wm_store
from ..database import get_db
from ..models import (
    AddOn, Country, CoverageArea, LanguageStyle, Package, LegalText, MusicStyle, Occasion, QuoteRequest, SpotLength, Station, TimeSlot, Tonality, Voice,
)
from ..pricing import QuoteError, calculate_quote
from ..schemas import (
    Catalog, DemoAudioIn, LegalTextOut, QuoteIn, QuoteOut, QuoteRequestCreated, QuoteRequestIn, ScriptOut, ScriptRequestIn,
)
from ..settings_store import get_settings

router = APIRouter(prefix="/api", tags=["Konfigurator"])


def _active(db: Session, model):
    return db.query(model).filter(model.active.is_(True)).order_by(model.sort_order, model.id).all()


@router.get("/catalog", response_model=Catalog, summary="Alle buchbaren Produkte")
def catalog(db: Session = Depends(get_db)):
    cfg = get_settings(db)
    return Catalog(
        currency=cfg["currency"],
        countries=_active(db, Country),
        ad_tax_rate_bp=cfg["ad_tax_rate_bp"],
        min_order_cent=cfg["min_order_cent"],
        studio_price_cent=cfg["studio_price_cent"],
        ai_enabled=ai.is_enabled(),
        tts_enabled=audio.tts_enabled(),
        audio_tags=audio.tts_enabled() and audio.supports_audio_tags(),
        occasions=_active(db, Occasion),
        tonalities=_active(db, Tonality),
        language_styles=_active(db, LanguageStyle),
        voices=_active(db, Voice),
        music_styles=_active(db, MusicStyle),
        stations=_active(db, Station),
        time_slots=_active(db, TimeSlot),
        spot_lengths=_active(db, SpotLength),
        addons=_active(db, AddOn),
        packages=_active(db, Package),
        coverage_areas=_active(db, CoverageArea),
    )


@router.post("/quote", response_model=QuoteOut, summary="Preis für eine Konfiguration berechnen")
def quote(data: QuoteIn, db: Session = Depends(get_db)):
    try:
        return calculate_quote(db, data)
    except QuoteError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/quote-requests", response_model=QuoteRequestCreated, status_code=201,
             summary="Angebotsanfrage absenden")
def create_quote_request(data: QuoteRequestIn, db: Session = Depends(get_db)):
    if not data.configuration.items and data.configuration.package_id is None:
        raise HTTPException(422, "Bitte ein Komplettpaket wählen oder mindestens einen Sender oder Stream buchen.")
    # Preis wird serverseitig neu berechnet – Werte aus dem Browser werden nie übernommen.
    try:
        result = calculate_quote(db, data.configuration)
    except QuoteError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    consent = {t.key: {"accepted_at": now, "version": t.version, "title": t.title}
               for t in db.query(LegalText).filter(LegalText.key.in_(["agb", "datenschutz"]))}
    req = QuoteRequest(
        consent=consent,
        customer_name=data.customer_name,
        company=data.company,
        street=data.street,
        zip_code=data.zip_code,
        city=data.city,
        email=data.email,
        phone=data.phone,
        message=data.message,
        configuration=data.configuration.model_dump(),
        brief=data.brief.model_dump(),
        quote=result.model_dump(),
    )
    db.add(req)
    db.commit()
    return QuoteRequestCreated(
        id=req.id, quote=result, pdf_url=f"/api/quote-requests/{req.id}/pdf?token={pdf.pdf_token(req.id)}",
    )


@router.get("/quote-requests/{req_id}/pdf", summary="PDF-Kostenaufstellung (signierter Link)",
            response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def quote_request_pdf(req_id: int, token: str, db: Session = Depends(get_db)):
    req = db.get(QuoteRequest, req_id)
    if req is None or not pdf.verify_pdf_token(token, req_id):
        raise HTTPException(404, "Nicht gefunden")
    return _pdf_response(req, db)


def pdf_bytes(req: QuoteRequest, db: Session) -> bytes:
    design = theme.get_theme(db)
    return pdf.build_request_pdf(req, get_settings(db)["company_info"], design["accent"],
                                 branding.pdf_image_path(branding.get_logo(db)), design["tagline"])


def _pdf_response(req: QuoteRequest, db: Session) -> Response:
    content = pdf_bytes(req, db)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="onaircraft-anfrage-{req.id}.pdf"'})


@router.post("/generate-script", response_model=ScriptOut, summary="Spot-Text per KI vorschlagen")
async def generate_script(data: ScriptRequestIn, request: Request, db: Session = Depends(get_db)):
    def active(model, item_id: int, label: str):
        obj = db.get(model, item_id)
        if obj is None or not obj.active:
            raise HTTPException(422, f"{label} nicht verfügbar")
        return obj

    occasion = active(Occasion, data.occasion_id, "Anlass")
    length = active(SpotLength, data.spot_length_id, "Spotlänge")
    tonality = active(Tonality, data.tonality_id, "Tonalität")
    style = active(LanguageStyle, data.language_style_id, "Sprachstil")
    try:
        ai.check_rate_limit(request.client.host if request.client else "unknown")
        script = await ai.generate_script(
            occasion=occasion.name, seconds=length.seconds, tonality=tonality.name,
            style_instruction=style.instruction, firma=data.firma, botschaft=data.botschaft, cta=data.cta,
            audio_tags=audio.tts_enabled() and audio.supports_audio_tags(), delivery_hint=tonality.delivery_hint,
        )
    except ai.ScriptError as e:
        raise HTTPException(e.status, str(e)) from e
    return ScriptOut(script=script)


# --------------------------------------------------------------------------- Hörproben

def _wav(data: bytes) -> Response:
    # no-store: Hörproben nicht im Browser-Cache ablegen
    return Response(data, media_type="audio/wav", headers={"Cache-Control": "no-store"})


def _tts_voice(db: Session, voice_id: int) -> Voice:
    voice = db.get(Voice, voice_id)
    if voice is None or not voice.active:
        raise HTTPException(404, "Stimme nicht verfügbar")
    if not voice.has_tts or not audio.tts_enabled():
        raise HTTPException(503, "Für diese Stimme ist keine KI-Stimme eingerichtet.")
    return voice


_timing = logging.getLogger("uvicorn.error")  # erscheint im Server-Terminal


def tts_settings(voice: Voice, tonality: Tonality | None = None, script: str = "",
                 seconds: int | None = None) -> dict:
    """ElevenLabs-Einstellungen aus Stimme + Tonalität; bei v2/Flash Tempo passend zur Spotlänge."""
    def pick(field):
        value = getattr(tonality, field) if tonality is not None else None
        return (value if value is not None else getattr(voice, field)) / 10_000

    speed = voice.speed_bp / 10_000 * ((tonality.speed_bp or 10_000) / 10_000 if tonality else 1)
    if seconds and script and not audio.supports_audio_tags():
        # Sprechtempo ~2,5 Wörter/s: zu langen Text etwas schneller sprechen, damit er in den Spot passt
        speed = max(speed, audio.spoken_words(script) / ai.WORDS_PER_SECOND / (0.95 * seconds))
    return audio.voice_settings(pick("stability_bp"), voice.similarity_bp / 10_000, pick("style_bp"), speed)


async def render_spot(db: Session, voice: Voice, script: str, music_style_id: int | None,
                      watermark: bool, settings_: dict | None = None):
    """Spot aus Text, Stimme und Musik mischen und mastern (48 kHz Stereo) – mit oder ohne Wasserzeichen."""
    cfg = get_settings(db)
    wm_cfg = wm_store.get_config(db)
    levels = music_mix.get_levels(db)
    music_path = _music_path(db, music_style_id)
    style = db.get(MusicStyle, music_style_id) if music_path else None
    music_gain = (style.gain_bp or 10_000) / 10_000 if style else 1.0
    started = time.perf_counter()
    # Sprache und (gesprochenes) Wasserzeichen gleichzeitig bei ElevenLabs anfragen
    jobs = [audio.synthesize(voice.elevenlabs_voice_id, script, settings_ or tts_settings(voice))]
    spoken_wm = watermark and wm_cfg["mode"] == "text"
    if spoken_wm:
        jobs.append(audio.synthesize(voice.elevenlabs_voice_id, cfg["watermark_text"]))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    if isinstance(results[0], Exception):
        raise results[0]
    tts_done = time.perf_counter()

    def work():  # rechenintensiv → im Thread, damit der Server weiter Anfragen bedient
        speech = audio.decode(results[0])
        wm = None
        if spoken_wm:
            # Ersatz-Piepton, falls der Wasserzeichen-Text nicht erzeugt werden konnte
            wm = audio.beep() if isinstance(results[1], Exception) else audio.decode(results[1])
        elif watermark:
            try:
                wm = wm_store.load(wm_cfg)  # eigene Audiodatei
            except audio.AudioError:
                wm = audio.beep()
        music = audio.decode_file(music_path, channels=2) if music_path else None
        mixed = audio.mix(speech, music, wm, cfg["watermark_interval_s"], wm_cfg["volume"] / 100,
                          bed_level=levels["mix_bed_level"] / 100, open_level=levels["mix_open_level"] / 100,
                          music_gain=music_gain)
        return audio.master(mixed, cfg["master_lufs"], cfg["master_ceiling_dbtp"])

    spot = await run_in_threadpool(work)
    _timing.info("Spot erstellt: ElevenLabs %.1f s, Mischen & Mastering %.1f s",
                 tts_done - started, time.perf_counter() - tts_done)
    return spot


def _music_path(db: Session, music_style_id: int | None) -> Path | None:
    if music_style_id is None:
        return None
    style = db.get(MusicStyle, music_style_id)
    if style is None or not style.audio_file or not (audio.MUSIC_DIR / style.audio_file).exists():
        return None
    return audio.MUSIC_DIR / style.audio_file


def _music_gain(db: Session, music_style_id: int | None) -> int:
    style = db.get(MusicStyle, music_style_id) if music_style_id else None
    return style.gain_bp if style else 10_000


def _preview_cache(*parts) -> Path:
    """Fertige Hörproben zwischenspeichern – gleiche Kombination wird sofort ausgeliefert."""
    key = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return audio.MEDIA_DIR / "cache" / "preview" / f"{key}.wav"


async def render_voice(voice: Voice, script: str, settings_: dict | None = None):
    """Nur die Sprache: 48 kHz Stereo, True Peak −1 dBTP, ohne Kompression/Lautheitsanhebung."""
    speech = audio.decode(await audio.synthesize(voice.elevenlabs_voice_id, script,
                                                 settings_ or tts_settings(voice)), channels=2)
    return await run_in_threadpool(audio.normalize_true_peak, speech, -1.0)


@router.get("/voices/{voice_id}/sample", summary="Kurze Stimmprobe (KI-Stimme)",
            response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def voice_sample(voice_id: int, request: Request, db: Session = Depends(get_db)):
    voice = _tts_voice(db, voice_id)
    text = f"Hallo, ich bin {voice.name}. So klingt Ihr Radiospot mit meiner Stimme."
    cfg = get_settings(db)
    settings_ = tts_settings(voice)
    cache = _preview_cache("sample", voice.elevenlabs_voice_id, audio.MODEL, text, settings_,
                           cfg["master_lufs"], cfg["master_ceiling_dbtp"])
    if cache.exists():
        return _wav(cache.read_bytes())
    try:
        audio.check_rate_limit(request.client.host if request.client else "unknown")
        speech = audio.decode(await audio.synthesize(voice.elevenlabs_voice_id, text, settings_))
        data = await run_in_threadpool(lambda: audio.preview_wav(
            audio.master(audio.mix(speech), cfg["master_lufs"], cfg["master_ceiling_dbtp"])))
    except audio.AudioError as e:
        raise HTTPException(e.status, str(e)) from e
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return _wav(data)


@router.post("/demo-audio", summary="Hörprobe: Text + Stimme + Musik, mit Wasserzeichen",
             response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def demo_audio(data: DemoAudioIn, request: Request, db: Session = Depends(get_db)):
    voice = _tts_voice(db, data.voice_id)
    cfg = get_settings(db)
    music_path = _music_path(db, data.music_style_id)
    tonality = db.get(Tonality, data.tonality_id) if data.tonality_id else None
    length = db.get(SpotLength, data.spot_length_id) if data.spot_length_id else None
    settings_ = tts_settings(voice, tonality, data.script, length.seconds if length else None)
    cache = _preview_cache("demo", voice.elevenlabs_voice_id, audio.MODEL, data.script.strip(), settings_,
                           music_path.name if music_path else "",
                           wm_store.cache_key(wm_store.get_config(db), cfg["watermark_text"]),
                           music_mix.get_levels(db), _music_gain(db, data.music_style_id),
                           cfg["watermark_interval_s"], cfg["master_lufs"], cfg["master_ceiling_dbtp"])
    if cache.exists():
        return _wav(cache.read_bytes())
    try:
        audio.check_rate_limit(request.client.host if request.client else "unknown")
        spot = await render_spot(db, voice, data.script, data.music_style_id, watermark=True, settings_=settings_)
        data_wav = await run_in_threadpool(audio.preview_wav, spot)
    except audio.AudioError as e:
        raise HTTPException(e.status, str(e)) from e
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data_wav)
    return _wav(data_wav)


@router.get("/legal/{key}", response_model=LegalTextOut, summary="Rechtstext (AGB, Datenschutz)")
def legal_text(key: str, db: Session = Depends(get_db)):
    text = db.query(LegalText).filter_by(key=key).first()
    if text is None:
        raise HTTPException(404, "Text nicht gefunden")
    return text
