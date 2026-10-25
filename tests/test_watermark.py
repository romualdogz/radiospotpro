import io
import re
import wave

import numpy as np

from app import audio, watermark
from tests.test_audio import _login, tone, tts  # noqa: F401  (Fixture tts)


def _csrf(client, path="/admin/settings"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def _upload(client, name="jingle.wav", content=None, **extra):
    content = content if content is not None else audio.to_wav(tone(1.0, 880))
    return client.post("/admin/settings", data={"csrf": _csrf(client), **extra},
                       files={"watermark_upload": (name, content, "audio/wav")})


def _demo(client):
    r = client.post("/api/demo-audio", json={"voice_id": 1, "script": "Jetzt neu in Wien!"})
    assert r.status_code == 200
    with wave.open(io.BytesIO(r.content)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def test_own_file_replaces_spoken_watermark(client, db, tts):
    _login(client)
    assert "Gesprochener Text" in client.get("/admin/settings").text
    _demo(client)
    assert [t for _, t in tts] == ["Jetzt neu in Wien!", "Hörprobe von onaircraft"]

    r = _upload(client, watermark_mode="text")
    assert "Einstellungen gespeichert" in r.text
    cfg = watermark.get_config(db)
    assert cfg["mode"] == "file" and cfg["file"].startswith("wm-")  # Upload → automatisch verwenden
    assert client.get("/admin/settings/watermark-audio").content.startswith(b"RIFF")

    tts.clear()
    _demo(client)  # neuer Cache-Schlüssel → neu gemischt, aber ohne Wasserzeichen-Text bei ElevenLabs
    assert [t for _, t in tts] == ["Jetzt neu in Wien!"]


def test_volume_changes_preview_and_cache(client, db, tts):
    _login(client)
    _upload(client)
    loud = _demo(client)
    client.post("/admin/settings", data={"csrf": _csrf(client), "watermark_mode": "file", "watermark_volume": "5"})
    assert watermark.get_config(db)["volume"] == 5
    quiet = _demo(client)
    assert not np.array_equal(loud, quiet)  # neuer Cache-Eintrag, anders gemischt


def test_mix_uses_watermark_level():
    voice = tone(4.0, 220, 0.5)
    wm = tone(0.5, 1000, 1.0)
    quiet = audio.mix(voice, None, wm, 7, 0.1)
    loud = audio.mix(voice, None, wm, 7, 0.8)
    base = audio.mix(voice)
    assert np.abs(loud - base).max() > 6 * np.abs(quiet - base).max()


def test_invalid_files_and_remove(client, db, tts):
    _login(client)
    for name, content, msg in [("x.txt", b"hallo", "MP3-, WAV-, OGG- oder FLAC"),
                               ("x.wav", b"kein audio", "nicht als Audio gelesen"),
                               ("lang.wav", audio.to_wav(tone(20.0)), "20.0 s lang"),
                               ("stumm.wav", audio.to_wav(np.zeros(48_000, np.float32)), "stumm")]:
        assert msg in _upload(client, name, content).text, name
    assert watermark.get_config(db)["file"] == ""
    r = client.post("/admin/settings", data={"csrf": _csrf(client), "watermark_mode": "file"})
    assert "bitte zuerst eine Audiodatei hochladen" in r.text

    _upload(client)
    path = watermark.get_config(db)["path"]
    client.post("/admin/settings", data={"csrf": _csrf(client), "watermark_mode": "file", "watermark_remove": "on"})
    cfg = watermark.get_config(db)
    assert cfg["mode"] == "text" and cfg["file"] == "" and not path.exists()
    assert client.get("/admin/settings/watermark-audio").status_code == 404


def test_missing_file_falls_back_to_text(client, db, tts):
    _login(client)
    _upload(client)
    watermark.get_config(db)["path"].unlink()
    assert watermark.get_config(db)["mode"] == "text"
    tts.clear()
    _demo(client)
    assert "Hörprobe von onaircraft" in [t for _, t in tts]


def test_short_preview_still_gets_watermark():
    voice = tone(0.6, 220, 0.5)  # Hörprobe kürzer als 2 s
    wm = tone(0.3, 1000, 1.0)
    assert np.abs(audio.mix(voice, None, wm) - audio.mix(voice)).max() > 0.1
