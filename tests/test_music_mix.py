import io
import re
import wave

import numpy as np

from app import audio, music_mix
from app.models import MusicStyle
from tests.test_audio import _login, tone, tts  # noqa: F401  (Fixture tts)

SR = audio.SAMPLE_RATE


def _csrf(client, path="/admin/settings"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def _segments(out, voice_len):
    """Spitzenpegel der Musik im Intro (vor der Stimme) – und Mischung während der Stimme."""
    intro = out[int(0.6 * SR):int(1.1 * SR)]
    under = out[int(1.6 * SR):int(1.5 * SR) + voice_len - int(0.1 * SR)]
    return float(np.abs(intro).max()), under


def test_mix_levels_and_music_gain():
    voice = np.zeros(int(3 * SR), np.float32)  # stumme „Stimme“ → nur die Musik bleibt hörbar
    voice[0] = 1e-3
    music = audio.stereo(tone(2.0, 330, 1.0))
    intro, under = _segments(audio.mix(voice, music), len(voice))
    assert abs(intro - 0.45) < 0.02 and abs(float(np.abs(under).max()) - 0.14) < 0.02  # Standard wie bisher

    intro, under = _segments(audio.mix(voice, music, bed_level=0.05, open_level=0.8), len(voice))
    assert abs(intro - 0.8) < 0.03 and abs(float(np.abs(under).max()) - 0.05) < 0.01
    intro, _ = _segments(audio.mix(voice, music, music_gain=0.5), len(voice))
    assert abs(intro - 0.225) < 0.02


def test_settings_page_saves_levels(client, db):
    _login(client)
    page = client.get("/admin/settings").text
    assert "Musik unter der Stimme" in page and 'name="mix_bed_level"' in page
    r = client.post("/admin/settings", data={"csrf": _csrf(client), "mix_bed_level": "20", "mix_open_level": "70"})
    assert "Einstellungen gespeichert" in r.text
    assert music_mix.get_levels(db) == {"mix_bed_level": 20, "mix_open_level": 70}
    client.post("/admin/settings", data={"csrf": _csrf(client), "mix_bed_level": "500"})
    assert music_mix.get_levels(db)["mix_bed_level"] == 60  # auf das Maximum begrenzt
    client.post("/admin/settings", data={"csrf": _csrf(client)})  # Felder fehlen → Werte bleiben
    assert music_mix.get_levels(db)["mix_open_level"] == 70


def test_music_gain_field_and_preview_cache(client, db, tts):
    _login(client)
    token = _csrf(client, "/admin/music-styles/new")
    r = client.post("/admin/music-styles/new", data={"csrf": token, "name": "Pop", "gain_bp": "0,7", "sort_order": "1",
                                                     "active": "on"},
                    files={"audio_file": ("pop.wav", audio.to_wav(tone(2, 220)), "audio/wav")})
    assert "gespeichert" in r.text
    style = db.query(MusicStyle).filter_by(name="Pop").one()
    assert style.gain_bp == 7000
    r = client.post(f"/admin/music-styles/{style.id}", data={"csrf": token, "name": "Pop", "gain_bp": "9",
                                                             "sort_order": "1", "active": "on"})
    assert "zwischen 0,2 und 3" in r.text

    def demo():
        r = client.post("/api/demo-audio", json={"voice_id": 1, "music_style_id": style.id,
                                                 "script": "Jetzt neu in Wien, gleich ums Eck!"})
        assert r.status_code == 200
        with wave.open(io.BytesIO(r.content)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    first = demo()
    tts.clear()
    assert np.array_equal(first, demo()) and tts == []  # aus dem Speicher
    client.post("/admin/settings", data={"csrf": _csrf(client), "mix_bed_level": "40"})
    assert not np.array_equal(first, demo())  # neue Lautstärke → neu gemischt
