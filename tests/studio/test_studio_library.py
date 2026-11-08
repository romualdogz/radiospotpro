"""Schritt 3: Bibliothek (SFX/Musik/Atmo von onaircraft), Loop, Fade-Kurven."""
import numpy as np
import pytest

from app import audio
from studio import render
from studio.accounts import create_user
from studio.models import Library, LibraryItem, StudioUser
from studio.projects import ProjectData

from .conftest import ADMIN, csrf_of, login
from .test_studio_editor import SR, run_queue, tone

PRO = ("pro@example.com", "pro-passwort-1")


def _upload_to_library(client, lib_id, files, category="sfx", tags=""):
    return client.post(f"/admin/library/{lib_id}/upload", data={"category": category, "tags": tags,
                                                                "csrf": csrf_of(client, f"/admin/library/{lib_id}")},
                       files=[("files", (n, d, "audio/wav")) for n, d in files], follow_redirects=True)


@pytest.fixture()
def lib(sclient, sdb):
    """Admin legt eine Sammlung an und lädt zwei Dateien hoch; danach ist niemand angemeldet."""
    login(sclient, *ADMIN)
    res = sclient.post("/admin/library", data={"name": "onaircraft SFX", "for_all": "1", "license_note": "Lizenz X",
                                               "csrf": csrf_of(sclient, "/admin/library")}, follow_redirects=True)
    lib = sdb.query(Library).one()
    res = _upload_to_library(sclient, lib.id, [("tuer.wav", tone(1.0)), ("kaputt.wav", b"nix" * 50)], tags="tür, haus")
    assert "1 Datei(en) hinzugefügt" in res.text and "kaputt.wav" in res.text
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    create_user(sdb, *PRO, "pro")
    return lib


def _h(client):
    return {"X-CSRF-Token": csrf_of(client, "/")}


def _save(client, h, clips, length=5):
    p = client.post("/api/projects", json={"name": "P", "length": length}, headers=h).json()
    res = client.put(f"/api/projects/{p['id']}", json={"name": "P", "data": {**p["data"], "clips": clips}}, headers=h)
    return p["id"], res


def test_library_visible_and_usable(sclient, sdb, lib):
    login(sclient, *PRO)
    h = _h(sclient)
    data = sclient.get("/api/library").json()
    assert [i["name"] for i in data["items"]] == ["tuer"]
    item = data["items"][0]
    assert item["license_note"] == "Lizenz X" and item["tags"] == "tür, haus" and item["category"] == "sfx"
    assert sclient.get(f"/api/library/{item['id']}/audio").status_code == 200
    assert len(sclient.get(f"/api/library/{item['id']}/peaks").json()) == 50
    pid, res = _save(sclient, h, [{"id": "c", "lib_id": item["id"], "track": "sfx", "start": 1, "duration": 1}])
    assert res.status_code == 200, res.text
    assert sclient.get("/api/me").json()["used_bytes"] == 0  # Bibliothek zählt nicht zum Speicher
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    run_queue()
    assert sclient.get(f"/api/exports/{ex['id']}").json()["status"] == "done"


def test_private_library_needs_grant(sclient, sdb, lib):
    lib.for_all = False
    sdb.commit()
    item = sdb.query(LibraryItem).one()
    login(sclient, *PRO)
    h = _h(sclient)
    assert sclient.get("/api/library").json()["items"] == []
    assert sclient.get(f"/api/library/{item.id}/audio").status_code == 404
    _, res = _save(sclient, h, [{"id": "c", "lib_id": item.id, "track": "sfx", "start": 0, "duration": 1}])
    assert res.status_code == 422
    # Admin schaltet die Sammlung für das Konto frei
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    login(sclient, *ADMIN)
    pro = sdb.query(StudioUser).filter_by(email=PRO[0]).one()
    page = sclient.get("/admin/users").text
    assert 'name="libraries"' in page
    sclient.post(f"/admin/users/{pro.id}", data={"role": "pro", "active": "1", "quota_mb": "100", "libraries": [str(lib.id)],
                                                "csrf": csrf_of(sclient, "/admin/users")})
    sdb.refresh(pro)
    assert pro.libraries == [lib.id]
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    login(sclient, *PRO)
    assert len(sclient.get("/api/library").json()["items"]) == 1


def test_clip_needs_exactly_one_source(sclient, sdb, lib):
    item = sdb.query(LibraryItem).one()
    login(sclient, *PRO)
    h = _h(sclient)
    _, res = _save(sclient, h, [{"id": "c", "track": "sfx", "start": 0, "duration": 1}])
    assert res.status_code == 422
    _, res = _save(sclient, h, [{"id": "c", "lib_id": item.id, "asset_id": 1, "track": "sfx", "start": 0, "duration": 1}])
    assert res.status_code == 422


def test_used_item_cannot_be_deleted_but_deactivated(sclient, sdb, lib):
    item = sdb.query(LibraryItem).one()
    login(sclient, *PRO)
    pid, _ = _save(sclient, _h(sclient), [{"id": "c", "lib_id": item.id, "track": "sfx", "start": 0, "duration": 1}])
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    login(sclient, *ADMIN)
    page = sclient.get(f"/admin/library/{lib.id}").text
    assert "1×" in page
    res = sclient.post(f"/admin/library/items/{item.id}/delete", data={"csrf": csrf_of(sclient, "/admin/library")},
                       follow_redirects=True)
    assert "stattdessen deaktivieren" in res.text and sdb.get(LibraryItem, item.id) is not None
    sclient.post(f"/admin/library/items/{item.id}", data={"name": "Tür", "category": "sfx", "tags": "", "active": "",
                                                         "csrf": csrf_of(sclient, "/admin/library")})
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    login(sclient, *PRO)
    h = _h(sclient)
    assert sclient.get("/api/library").json()["items"] == []        # nicht mehr in der Auswahl …
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    run_queue()
    assert sclient.get(f"/api/exports/{ex['id']}").json()["status"] == "done"  # … bestehendes Projekt klingt weiter


def test_pro_cannot_open_library_admin(sclient, sdb, lib):
    login(sclient, *PRO)
    assert sclient.get("/admin/library").status_code == 403
    assert sclient.post(f"/admin/library/{lib.id}/upload", data={"csrf": csrf_of(sclient, "/")},
                        files=[("files", ("a.wav", tone(), "audio/wav"))]).status_code == 403


def test_cli_import_library(sdb, tmp_path, capsys):
    from studio.cli import main
    (tmp_path / "sub").mkdir()
    (tmp_path / "regen.wav").write_bytes(tone(2.0))
    (tmp_path / "sub" / "wind.wav").write_bytes(tone(1.0))
    (tmp_path / "liesmich.txt").write_text("x")
    assert main(["import-library", str(tmp_path), "--library", "Atmos", "--category", "atmo", "--tags", "draußen"]) == 0
    items = sdb.query(LibraryItem).order_by(LibraryItem.name).all()
    assert [(i.name, i.category, i.tags) for i in items] == [("regen", "atmo", "draußen"), ("wind", "atmo", "draußen")]
    assert "2 von 2" in capsys.readouterr().out


# --------------------------------------------------------------------------- Loop und Fades

def test_loop_validation(sclient):
    login(sclient, *ADMIN)
    h = _h(sclient)
    a = sclient.post("/api/assets", content=tone(1.0), headers={**h, "X-Filename": "a.wav"}).json()
    clip = {"id": "c", "asset_id": a["id"], "track": "atmo", "start": 0, "duration": 4}
    assert _save(sclient, h, [clip])[1].status_code == 422                     # länger als die Datei
    assert _save(sclient, h, [{**clip, "loop": True}])[1].status_code == 200    # mit Loop erlaubt
    assert _save(sclient, h, [{**clip, "loop": True, "offset": 1.5}])[1].status_code == 422  # Start hinter Dateiende


def test_loop_render_is_continuous(tmp_path):
    f = tmp_path / "n.wav"
    noise = np.random.default_rng(0).normal(0, 0.2, SR).astype(np.float32)  # 1 s Rauschen
    f.write_bytes(audio.to_wav(noise))
    data = ProjectData.model_validate({"length": 4, "clips": [
        {"id": "a", "asset_id": 1, "track": "atmo", "start": 0, "offset": 0.25, "duration": 3.5, "loop": True}]})
    out = render.mix_project(data, {("a", 1): f})[:, 0]
    assert np.abs(out[int(3.5 * SR) + 10:]).max() == 0
    rms = [np.sqrt(np.mean(out[i:i + 2400] ** 2)) for i in range(0, int(3.5 * SR) - 2400, 2400)]
    assert min(rms) > 0.15 and max(rms) < 0.25  # keine Lücken oder Pegelsprünge an den Nahtstellen
    assert np.allclose(out[:SR // 2], np.frombuffer(audio.to_wav(noise)[44:], "<i2")[SR // 4: SR // 4 + SR // 2] / 32768, atol=1e-3)


def test_fade_curves():
    x = np.array([0, 0.25, 0.5, 1.0], dtype=np.float32)
    assert np.allclose(render.fade_curve(x, "linear"), x)
    assert np.allclose(render.fade_curve(x, "smooth"), [0, 0.1464, 0.5, 1.0], atol=1e-3)


def test_fade_out_follows_clip_end_even_when_cut(tmp_path):
    f = tmp_path / "t.wav"
    f.write_bytes(audio.to_wav(np.full(4 * SR, 0.5, dtype=np.float32)))
    data = ProjectData.model_validate({"length": 2, "clips": [
        {"id": "a", "asset_id": 1, "track": "music", "start": 0, "duration": 4, "fade_out": 2, "fade_curve": "linear"}]})
    out = render.mix_project(data, {("a", 1): f})[:, 0]
    assert out[SR - 1] == pytest.approx(0.5, abs=0.01)   # Fade beginnt erst bei 2 s = Projektende
    assert out[-1] == pytest.approx(0.5, abs=0.01)


def test_old_clips_keep_linear_fades():
    d = ProjectData.model_validate({"clips": [{"id": "a", "asset_id": 1, "track": "voice", "start": 0, "duration": 1}]})
    assert d.clips[0].fade_curve == "linear" and d.clips[0].loop is False
