"""Schritt 4: Hüllkurven, Ducking, Loudness-Normalisierung."""
import numpy as np
import pytest

from app import audio
from studio import automation, render
from studio.projects import ProjectData

from .conftest import ADMIN, csrf_of, login

SR = audio.SAMPLE_RATE


@pytest.fixture()
def files(tmp_path):
    dc = tmp_path / "dc.wav"          # „Musik“: konstanter Pegel 0,5 – leicht nachzumessen
    dc.write_bytes(audio.to_wav(np.full(4 * SR, 0.5, dtype=np.float32)))
    t = np.arange(SR) / SR
    voice = tmp_path / "voice.wav"    # 1 s Sprache (Sinus)
    voice.write_bytes(audio.to_wav((np.sin(2 * np.pi * 300 * t) * 0.3).astype(np.float32)))
    return {("a", 1): dc, ("a", 2): voice}


def _project(**over):
    d = {"length": 4, "clips": [
        {"id": "m", "asset_id": 1, "track": "music", "start": 0, "duration": 4},
        {"id": "v", "asset_id": 2, "track": "voice", "start": 1, "duration": 1}]}
    d.update(over)
    return ProjectData.model_validate(d)


def test_envelope_changes_volume_over_time(files):
    data = _project(clips=[{"id": "m", "asset_id": 1, "track": "music", "start": 0, "duration": 4}],
                    tracks={"music": {"envelope": [{"t": 2, "db": -20}, {"t": 0, "db": 0}]}})
    assert [p.t for p in data.tracks["music"].envelope] == [0, 2]  # wird sortiert
    out = render.mix_project(data, files)[:, 0]
    assert out[10] == pytest.approx(0.5, abs=0.01)
    assert out[SR] == pytest.approx(0.5 * 10 ** (-10 / 20), abs=0.01)   # Mitte: −10 dB
    assert out[3 * SR] == pytest.approx(0.05, abs=0.005)                  # danach konstant −20 dB


def test_ducking_lowers_music_while_voice_speaks(files):
    on = render.mix_project(_project(tracks={"music": {"duck": True}}, ducking={"amount_db": 10}), files)[:, 0]
    off = render.mix_project(_project(), files)[:, 0]
    music_on = lambda s: off[int(s * SR)] - on[int(s * SR)]  # noqa: E731 – Differenz = Absenkung der Musik
    assert music_on(0.5) == pytest.approx(0, abs=1e-3)                          # vor der Sprache: voll
    assert music_on(1.5) == pytest.approx(0.5 * (1 - 10 ** (-0.5)), abs=0.01)   # während: −10 dB
    assert music_on(2.15) > 0.3                                                 # Haltezeit nach dem Wort
    assert music_on(3.9) < 0.02                                                 # danach wieder oben
    assert music_on(0.97) > 0.05                                                # setzt kurz vorher ein


def test_no_ducking_when_voice_muted(files):
    on = render.mix_project(_project(tracks={"music": {"duck": True}, "voice": {"mute": True}}), files)[:, 0]
    assert on[int(1.5 * SR)] == pytest.approx(0.5, abs=0.001)


def test_duck_curve_matches_reference():
    voice = np.full(300, -120.0)
    voice[100:150] = -20
    d = automation.duck_db(voice, 12, 0.5)
    assert d[99] < -1 and d[140] == pytest.approx(-12, abs=0.1) and d[160] == pytest.approx(-12, abs=0.1)
    assert d[299] > -3 and np.all(d <= 0)


def test_normalize_mode(tmp_path):
    from pathlib import Path
    m = audio.stereo(audio.decode_file(Path("app/static/demo-music/corporate-uplifting.wav"), 2))
    for target in (-23, -16):
        y = render.finish(m, target, "normalize")
        assert audio.loudness(y) == pytest.approx(target, abs=0.15) and audio.true_peak_db(y) <= -1.0
    # Normalisieren ändert die Dynamik nicht (reine Verstärkung)
    y = render.finish(m, -23, "normalize")
    ratio = y[1000:2000] / np.where(np.abs(m[1000:2000]) > 1e-4, m[1000:2000], 1)
    assert np.std(ratio[np.abs(m[1000:2000]) > 1e-4]) < 1e-3


def test_api_new_project_ducks_and_export_mode(sclient):
    login(sclient, *ADMIN)
    h = {"X-CSRF-Token": csrf_of(sclient, "/")}
    p = sclient.post("/api/projects", json={"name": "P"}, headers=h).json()
    tracks = p["data"]["tracks"]
    assert tracks["music"]["duck"] and tracks["atmo"]["duck"] and not tracks["sfx"]["duck"]
    assert p["data"]["ducking"]["amount_db"] == 10
    bad = {**p["data"], "tracks": {**tracks, "music": {**tracks["music"], "envelope": [{"t": 1, "db": 40}]}}}
    assert sclient.put(f"/api/projects/{p['id']}", json={"name": "P", "data": bad}, headers=h).status_code == 422
    assert sclient.post(f"/api/projects/{p['id']}/exports", json={"mode": "laut"}, headers=h).status_code == 422
