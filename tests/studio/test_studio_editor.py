"""Schritt 2: Dateien, Projekte, Mischung, Export-Warteschlange."""
import io
import wave
from datetime import timedelta

import numpy as np
import pytest

from app import audio
from studio import render, worker
from studio.accounts import create_user
from studio.config import settings
from studio.models import Export, StudioUser, now
from studio.projects import ProjectData

from .conftest import ADMIN, csrf_of, login

SR = audio.SAMPLE_RATE


def tone(seconds=2.0, freq=440, level=0.5) -> bytes:
    t = np.arange(int(seconds * SR)) / SR
    return audio.to_wav((np.sin(2 * np.pi * freq * t) * level).astype(np.float32))


def authed(client, who=ADMIN):
    login(client, *who)
    return {"X-CSRF-Token": csrf_of(client, "/")}


def upload(client, h, data=None, name="ton.wav"):
    return client.post("/api/assets", content=data if data is not None else tone(),
                       headers={**h, "X-Filename": name})


def project_with_clip(client, h, asset_id, length=5, **clip):
    p = client.post("/api/projects", json={"name": "Spot", "length": length}, headers=h).json()
    c = {"id": "c1", "asset_id": asset_id, "track": "voice", "start": 0, "offset": 0, "duration": 2,
         "gain_db": 0, "fade_in": 0, "fade_out": 0, **clip}
    data = {**p["data"], "clips": [c]}
    res = client.put(f"/api/projects/{p['id']}", json={"name": "Spot", "data": data}, headers=h)
    assert res.status_code == 200, res.text
    return p["id"]


def run_queue():
    while (job_id := worker.claim_next()) is not None:
        worker.process(job_id)


# --------------------------------------------------------------------------- Dateien

def test_upload_and_peaks(sclient):
    h = authed(sclient)
    res = upload(sclient, h)
    assert res.status_code == 201, res.text
    a = res.json()
    assert a["name"] == "ton.wav" and abs(a["duration"] - 2.0) < 0.01
    peaks = sclient.get(f"/api/assets/{a['id']}/peaks").json()
    assert len(peaks) == 100 and max(peaks) == pytest.approx(127, abs=2)  # 0,5 → 127
    assert sclient.get(f"/api/assets/{a['id']}/audio").content[:4] == b"RIFF"
    assert sclient.get("/api/me").json()["used_bytes"] == a["size_bytes"]


@pytest.mark.parametrize("data,name,status", [
    (b"kein audio" * 100, "fake.wav", 422),
    (b"x" * 100, "bild.png", 415),
    (b"", "leer.wav", 400),
    (b"\0" * (6 * 1024 * 1024), "gross.wav", 413),
])
def test_upload_rejected(sclient, data, name, status):
    h = authed(sclient)
    assert upload(sclient, h, data, name).status_code == status
    assert sclient.get("/api/assets").json() == []
    assert not list((settings.media_dir / "users").rglob("*.part"))


def test_upload_needs_csrf_and_quota(sclient, sdb):
    login(sclient, *ADMIN)
    assert sclient.post("/api/assets", content=tone(), headers={"X-Filename": "a.wav"}).status_code == 403
    user = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    user.quota_mb = 0
    sdb.commit()
    assert upload(sclient, {"X-CSRF-Token": csrf_of(sclient, "/")}).status_code == 413


def test_other_users_data_is_invisible(sclient, sdb):
    h = authed(sclient)
    asset = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, asset["id"])
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})

    create_user(sdb, "andere@example.com", "anderes-pw-123", "pro")
    h2 = authed(sclient, ("andere@example.com", "anderes-pw-123"))
    for path in (f"/api/assets/{asset['id']}/audio", f"/api/assets/{asset['id']}/peaks",
                 f"/api/projects/{pid}", f"/api/projects/{pid}/exports"):
        assert sclient.get(path).status_code == 404, path
    assert sclient.get("/api/assets").json() == [] and sclient.get("/api/projects").json() == []
    assert sclient.delete(f"/api/projects/{pid}", headers=h2).status_code == 404
    # fremde Datei im eigenen Projekt verwenden geht auch nicht
    own = sclient.post("/api/projects", json={"name": "X"}, headers=h2).json()
    bad = {**own["data"], "clips": [{"id": "c", "asset_id": asset["id"], "track": "music", "start": 0, "duration": 1}]}
    assert sclient.put(f"/api/projects/{own['id']}", json={"name": "X", "data": bad}, headers=h2).status_code == 422


def test_project_validation(sclient):
    h = authed(sclient)
    a = upload(sclient, h).json()
    p = sclient.post("/api/projects", json={"name": "P", "length": 30}, headers=h).json()

    def save(**clip):
        c = {"id": "c", "asset_id": a["id"], "track": "music", "start": 0, "offset": 0, "duration": 1, **clip}
        return sclient.put(f"/api/projects/{p['id']}", json={"name": "P", "data": {**p["data"], "clips": [c]}}, headers=h)

    assert save().status_code == 200
    assert save(track="drums").status_code == 422
    assert save(offset=1.5, duration=1).status_code == 422          # über das Dateiende hinaus
    assert save(fade_in=0.8, fade_out=0.8).status_code == 422       # Fades länger als Clip
    assert save(start=-1).status_code == 422
    res = sclient.put(f"/api/projects/{p['id']}", json={"name": "P", "data": {**p["data"], "length": 9999}}, headers=h)
    assert res.status_code == 422


def test_asset_in_use_cannot_be_deleted(sclient):
    h = authed(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    res = sclient.delete(f"/api/assets/{a['id']}", headers=h)
    assert res.status_code == 409 and "Spot" in res.json()["detail"]
    sclient.delete(f"/api/projects/{pid}", headers=h)
    assert sclient.delete(f"/api/assets/{a['id']}", headers=h).status_code == 204
    assert sclient.get("/api/me").json()["used_bytes"] == 0


# --------------------------------------------------------------------------- Mischung

def _wav_file(tmp_path, seconds=2.0, level=0.5):
    p = tmp_path / f"t{seconds}{level}.wav"
    p.write_bytes(tone(seconds, level=level))
    return p


def test_mix_places_clips_with_gain_fades_and_solo(tmp_path):
    f = _wav_file(tmp_path)
    data = ProjectData.model_validate({"length": 4, "clips": [
        {"id": "a", "asset_id": 1, "track": "voice", "start": 1.0, "offset": 0.5, "duration": 1.0, "gain_db": -6.0206},
        {"id": "b", "asset_id": 1, "track": "music", "start": 0, "duration": 2, "fade_in": 1.0},
    ], "tracks": {"music": {"mute": True}}})
    out = render.mix_project(data, {1: f})
    assert out.shape == (4 * SR, 2)
    assert np.abs(out[: SR - 10]).max() == 0                     # Musik stumm, Sprache erst ab 1 s
    assert np.abs(out[SR + 100: 2 * SR - 100]).max() == pytest.approx(0.25, abs=0.01)  # −6 dB
    assert np.abs(out[2 * SR + 10:]).max() == 0                  # Clip endet bei 2 s

    data.tracks["music"].mute = False
    data.tracks["music"].solo = True
    out = render.mix_project(data, {1: f})
    assert np.abs(out[SR + 100: 2 * SR]).max() == pytest.approx(0.5, abs=0.01)  # nur Musik
    assert np.abs(out[:2400]).max() < 0.03                       # Fade-in beginnt bei 0


def test_clip_past_project_end_is_cut(tmp_path):
    f = _wav_file(tmp_path, 3.0)
    data = ProjectData.model_validate({"length": 2, "clips": [
        {"id": "a", "asset_id": 1, "track": "sfx", "start": 1.5, "duration": 3.0}]})
    assert len(render.mix_project(data, {1: f})) == 2 * SR


def test_finish_limits_peaks_or_masters(tmp_path):
    loud = np.full((SR, 2), 1.5, dtype=np.float32) * np.sin(np.arange(SR) / 10)[:, None].astype(np.float32)
    assert audio.true_peak_db(render.finish(loud, None)) <= -0.9
    quiet = loud * 0.01
    assert np.allclose(render.finish(quiet, None), quiet)          # leise bleibt unverändert
    assert audio.loudness(render.finish(loud, -14)) == pytest.approx(-14, abs=0.2)


def test_finish_never_exceeds_true_peak_ceiling():
    """Extremes Material (übersteuerter Mix aus Ton mit Tremolo und Rauschen): Limiter allein landete bei −0,7 dBTP."""
    t = np.arange(4 * SR) / SR
    tone_ = np.sin(2 * np.pi * 220 * t) * 0.5 * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    noise = np.random.default_rng(2).normal(0, 0.1, len(t))
    mix = audio.stereo((tone_ * 2.4 + noise).astype(np.float32))
    for target in (None, -8):
        assert audio.true_peak_db(render.finish(mix, target)) <= -1.0


# --------------------------------------------------------------------------- Export

def test_export_end_to_end(sclient):
    h = authed(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"], length=3, start=0.5)
    res = sclient.post(f"/api/projects/{pid}/exports", json={"loudness": -14}, headers=h)
    assert res.status_code == 202 and res.json()["status"] == "queued"
    ex_id = res.json()["id"]
    assert sclient.get(f"/api/exports/{ex_id}/download").status_code == 409

    run_queue()  # eigener Prozess je Auftrag, wie im Betrieb
    e = sclient.get(f"/api/exports/{ex_id}").json()
    assert e["status"] == "done", e
    assert e["measured_lufs"] == pytest.approx(-14, abs=0.3) and e["measured_peak"] <= -0.9

    dl = sclient.get(f"/api/exports/{ex_id}/download")
    assert dl.status_code == 200 and 'filename="Spot_' in dl.headers["content-disposition"]
    with wave.open(io.BytesIO(dl.content)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (48000, 2, 3, 3 * SR)
    me = sclient.get("/api/me").json()
    assert me["used_bytes"] == a["size_bytes"] + e["size_bytes"] and me["exports_used"] == 1

    assert sclient.delete(f"/api/exports/{ex_id}", headers=h).status_code == 204
    assert sclient.get(f"/api/exports/{ex_id}").json()["status"] == "expired"
    assert sclient.get("/api/me").json()["exports_used"] == 1  # zählt weiter fürs Kontingent


def test_export_snapshot_and_missing_asset(sclient, sdb):
    h = authed(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    job = sdb.get(Export, ex["id"])
    job.snapshot["clips"][0]["asset_id"] = 999999  # Datei inzwischen weg
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(job, "snapshot")
    sdb.commit()
    run_queue()
    e = sclient.get(f"/api/exports/{ex['id']}").json()
    assert e["status"] == "failed" and "gelöscht" in e["error"]


def test_export_limits(sclient, sdb):
    h = authed(sclient)
    a = upload(sclient, h).json()
    empty = sclient.post("/api/projects", json={"name": "Leer"}, headers=h).json()
    assert sclient.post(f"/api/projects/{empty['id']}/exports", json={}, headers=h).status_code == 400
    pid = project_with_clip(sclient, h, a["id"])
    for _ in range(settings.max_queued_per_user):
        assert sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).status_code == 202
    assert sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).status_code == 429
    user = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    user.export_limit = 2
    sdb.commit()
    sdb.query(Export).update({"status": "done"})
    sdb.commit()
    res = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h)
    assert res.status_code == 403 and "Kontingent" in res.json()["detail"]
    assert sclient.post(f"/api/projects/{pid}/exports", json={"loudness": 0}, headers=h).status_code == 422


def test_cleanup_and_stale_jobs(sclient, sdb):
    h = authed(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    run_queue()
    job = sdb.get(Export, ex["id"])
    from studio.storage import export_path
    path = export_path(job)
    assert path.exists()
    job.finished_at = now() - timedelta(days=settings.export_days + 1)
    stale = Export(user_id=job.user_id, project_id=pid, name="x", snapshot=job.snapshot, status="running",
                   started_at=now() - timedelta(hours=1))
    sdb.add(stale)
    sdb.commit()
    assert worker.cleanup() == 1
    worker.recover_stale()
    sdb.expire_all()
    assert sdb.get(Export, ex["id"]).status == "expired" and not path.exists()
    assert sdb.get(Export, stale.id).status == "failed"


def test_render_timeout_kills_job(sclient, monkeypatch):
    h = authed(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)))
    run_queue()
    e = sclient.get(f"/api/exports/{ex['id']}").json()
    assert e["status"] == "failed" and "Zeitlimit" not in e["error"] and "Abgebrochen" in e["error"]
