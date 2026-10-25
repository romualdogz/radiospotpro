import io
import re
import shutil
import wave

import numpy as np
import pytest

from app import audio
from app.models import MusicStyle, SpotLength, Station, TimeSlot, Voice

SR = audio.SAMPLE_RATE


def tone(seconds: float, freq: float = 440, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


def test_mix_with_music_adds_intro_and_outro():
    voice, music = tone(4), np.column_stack([tone(3, 220), tone(3, 330)])  # Musik in Stereo
    out = audio.mix(voice, music)
    assert out.shape == (int(1.5 * SR) + len(voice) + int(2.5 * SR), 2)
    # Musik läuft im Intro (nach dem Fade-in), Stereo bleibt erhalten
    intro = out[int(0.8 * SR):int(1.0 * SR)]
    assert np.abs(intro).max() > 0.3 and not np.allclose(intro[:, 0], intro[:, 1])


def test_mix_without_music_and_watermark_positions():
    voice = np.zeros(int(20 * SR), np.float32)
    voice[0] = 0.5  # Stimme praktisch stumm, damit nur das Wasserzeichen hörbar ist
    out = audio.mix(voice, None, tone(1.0, 1000), watermark_every=7)
    pad = 0.3  # Stille vor der Stimme
    level = lambda t: float(np.abs(out[int((pad + t) * SR):int((pad + t + 0.5) * SR)]).max())
    # erstes Wasserzeichen nach 2 s (ab Dateibeginn), dann alle 7 s
    for t in (2.0, 9.0, 16.0):
        assert level(t - pad + 0.2) > 0.2, t
    for t in (5.0, 12.0):
        assert level(t - pad) < 0.01, t


def test_wav_roundtrip():
    data = audio.to_wav(tone(1))
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (SR, 1, SR)
    assert len(audio.decode(data)) == SR


def test_wav_24bit_stereo():
    x = np.column_stack([tone(1, amp=0.5), -tone(1, amp=0.5)])
    data = audio.to_wav(x, bits=24)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (48_000, 2, 3)
        raw = np.frombuffer(w.readframes(w.getnframes()), np.uint8).reshape(-1, 3)
    ints = (raw[:, 0].astype(np.int32) | raw[:, 1].astype(np.int32) << 8 | raw[:, 2].astype(np.int32) << 16)
    ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints).reshape(-1, 2) / 8_388_607
    assert np.allclose(ints, x, atol=1e-6)


def test_loudness_matches_reference():
    pyln = pytest.importorskip("pyloudnorm")
    rng = np.random.default_rng(3)
    x = np.column_stack([tone(5, 220, 0.3) + rng.standard_normal(5 * SR) * 0.02, tone(5, 330, 0.2)])
    assert abs(audio.loudness(x) - pyln.Meter(SR).integrated_loudness(x)) < 0.1


def test_master_hits_target_and_true_peak():
    pyln = pytest.importorskip("pyloudnorm")
    rng = np.random.default_rng(4)
    voice = tone(8, 180, 0.6) * (np.sin(np.arange(8 * SR) / SR * 2 * np.pi * 3) > 0)  # „Silben“
    music = np.column_stack([tone(5, 110, 0.4) + rng.standard_normal(5 * SR) * 0.05, tone(5, 165, 0.4)])
    out = audio.master(audio.mix(voice, music), -8, -1)
    assert out.shape[1] == 2
    assert abs(pyln.Meter(SR).integrated_loudness(out) - (-8)) < 0.2
    assert audio.true_peak_db(out) <= -1.0 + 0.05


@pytest.fixture()
def tts(db, monkeypatch):
    """ElevenLabs simulieren: jeder Text wird zu einem Ton mit textabhängiger Länge."""
    calls = type('Calls', (list,), {})()

    async def fake_synthesize(voice_id, text, settings_=None):
        calls.append((voice_id, text))
        settings_log.append(settings_)
        return audio.to_wav(tone(0.5 + len(text) / 100))

    settings_log = []

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    monkeypatch.setattr(audio, "synthesize", fake_synthesize)
    shutil.rmtree(audio.MEDIA_DIR / "cache", ignore_errors=True)  # Hörproben-Speicher je Test leeren
    db.add_all([Voice(name="Lena", elevenlabs_voice_id="abc"), Voice(name="Ohne KI"),
                Station(name="Radio A", price_per_second_cent=1000), TimeSlot(name="Tag"), SpotLength(seconds=20)])
    db.commit()
    calls.settings = settings_log  # type: ignore[attr-defined]
    return calls


def test_catalog_flags(client, tts):
    cat = client.get("/api/catalog").json()
    assert cat["tts_enabled"] is True
    assert [v["has_tts"] for v in cat["voices"]] == [True, False]
    assert "elevenlabs_voice_id" not in cat["voices"][0]  # Voice-ID bleibt intern


def test_voice_sample(client, tts):
    r = client.get("/api/voices/1/sample")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert tts == [("abc", "Hallo, ich bin Lena. So klingt Ihr Radiospot mit meiner Stimme.")]
    assert client.get("/api/voices/2/sample").status_code == 503  # Stimme ohne Voice-ID


def test_demo_audio_contains_watermark(client, tts):
    r = client.post("/api/demo-audio", json={"voice_id": 1, "script": "Jetzt neu in Wien!"})
    assert r.status_code == 200 and r.content.startswith(b"RIFF")
    with wave.open(io.BytesIO(r.content)) as w:  # Hörprobe fürs Web: mono, 32 kHz
        assert (w.getnchannels(), w.getframerate()) == (1, 32_000)
    texts = [t for _, t in tts]
    assert texts == ["Jetzt neu in Wien!", "Hörprobe von onaircraft"]


def test_demo_audio_text_limit(client, tts):
    assert client.post("/api/demo-audio", json={"voice_id": 1, "script": "x" * 1001}).status_code == 422


def _login(client):
    page = client.get("/admin/login").text
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})


def test_music_upload_and_clean_admin_audio(client, db, tts):
    _login(client)
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/music-styles/new").text).group(1)
    # ungültige Datei wird abgelehnt
    r = client.post("/admin/music-styles/new", data={"csrf": token, "name": "Kaputt", "sort_order": "1", "active": "on"},
                    files={"audio_file": ("kaputt.mp3", b"keine musik", "audio/mpeg")})
    assert "nicht als Audio gelesen" in r.text
    r = client.post("/admin/music-styles/new", data={"csrf": token, "name": "Pop", "sort_order": "1", "active": "on"},
                    files={"audio_file": ("pop.wav", audio.to_wav(tone(2, 220)), "audio/wav")},
                    follow_redirects=False)
    assert r.status_code == 303
    style = db.query(MusicStyle).filter_by(name="Pop").one()
    db.refresh(style)
    assert style.audio_file.endswith(".wav") and (audio.MUSIC_DIR / style.audio_file).exists()
    assert client.get(style.audio_url).status_code == 200  # Vorhören

    # Anfrage mit Musik → Admin lädt den Spot OHNE Wasserzeichen
    req = client.post("/api/quote-requests", json={
        "configuration": {"production": {"spot_length_id": 1, "voice_id": 1, "music_style_id": style.id},
                          "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
        "brief": {"script": "Jetzt neu in Wien!"},
        "customer_name": "Erika", "email": "erika@example.com",
        "street": "Gasse 1", "zip_code": "1010", "city": "Wien", "phone": "+43 1 1234",
        "accept_terms": True, "accept_privacy": True,
    }).json()
    tts.clear()
    r = client.get(f"/admin/requests/{req['id']}/audio/spot")
    assert r.status_code == 200 and "onaircraft-spot-" in r.headers["content-disposition"]
    assert [t for _, t in tts] == ["Jetzt neu in Wien!"]  # kein Wasserzeichen-Text
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 48_000, 3)
    spot_len = len(r.content)

    r = client.get(f"/admin/requests/{req['id']}/audio/voice")
    assert r.status_code == 200 and "onaircraft-sprache-" in r.headers["content-disposition"]
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 48_000, 3)
    assert len(r.content) < spot_len  # ohne Musik-Intro/-Outro kürzer
    assert client.get(f"/admin/requests/{req['id']}/audio/anderes").status_code == 404


def test_dashboard_lists_voices_without_id(client, tts):
    _login(client)
    page = client.get("/admin").text
    assert "keine ElevenLabs Voice-ID" in page and "Ohne KI" in page


def test_demo_audio_is_cached(client, tts):
    body = {"voice_id": 1, "script": "Zwischenspeicher-Test"}
    first = client.post("/api/demo-audio", json=body)
    calls = len(tts)
    second = client.post("/api/demo-audio", json=body)
    assert second.status_code == 200 and second.content == first.content
    assert len(tts) == calls  # kein weiterer ElevenLabs-Aufruf
    # anderer Text → neue Hörprobe
    client.post("/api/demo-audio", json={**body, "script": "Anderer Text"})
    assert len(tts) > calls


def test_voice_sample_is_cached(client, tts):
    client.get("/api/voices/1/sample")
    client.get("/api/voices/1/sample")
    assert len(tts) == 1



# --------------------------------------------------------------------------- Sprech-Dynamik

def test_prepare_text_depends_on_model():
    text = '[excited] Neu! <break time="0.5s" /> Jetzt [whispers] zugreifen.'
    assert audio.prepare_text(text, "eleven_v4") == '[excited] Neu! — Jetzt [whispers] zugreifen.'
    assert audio.prepare_text(text, "eleven_multilingual_v2") == 'Neu! <break time="0.5s" /> Jetzt zugreifen.'
    assert audio.spoken_words(text) == 3  # „Neu! Jetzt zugreifen.“


def test_voice_settings_per_model():
    assert audio.voice_settings(0.4, 0.8, 0.3, 1.1, "eleven_v4") == {"stability": 0.4, "similarity_boost": 0.8}
    assert audio.voice_settings(0.4, 0.8, 0.3, 1.5, "eleven_flash_v2_5") == {
        "stability": 0.4, "similarity_boost": 0.8, "style": 0.3, "speed": 1.2}


def test_tts_settings_from_voice_and_tonality(db, monkeypatch):
    from app.models import Tonality
    from app.routers.public import tts_settings
    voice = Voice(name="V", stability_bp=6000, similarity_bp=8000, style_bp=1000, speed_bp=10000)
    urgent = Tonality(name="dringend", stability_bp=4000, style_bp=4000, speed_bp=11000)
    monkeypatch.setattr(audio, "MODEL", "eleven_v4")
    assert tts_settings(voice, urgent) == {"stability": 0.4, "similarity_boost": 0.8}
    monkeypatch.setattr(audio, "MODEL", "eleven_multilingual_v2")
    assert tts_settings(voice, urgent) == {"stability": 0.4, "similarity_boost": 0.8, "style": 0.4, "speed": 1.1}
    assert tts_settings(voice) == {"stability": 0.6, "similarity_boost": 0.8, "style": 0.1, "speed": 1.0}
    # 50 Wörter in einem 15-Sekunden-Spot → schneller (max. 1,2)
    long_text = " ".join(["Wort"] * 50)
    assert tts_settings(voice, None, long_text, 15)["speed"] == 1.2
    assert tts_settings(voice, None, "Kurz und knapp.", 15)["speed"] == 1.0


def test_demo_uses_tonality(client, db, tts):
    from app.models import Tonality
    db.add(Tonality(name="dringend", stability_bp=3000))
    db.commit()
    client.post("/api/demo-audio", json={"voice_id": 1, "script": "Jetzt!", "tonality_id": 1, "spot_length_id": 1})
    assert tts.settings[0]["stability"] == 0.3
