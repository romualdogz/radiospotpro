"""KI im Studio: Stimmen-Freigabe, Textvorschläge, Einsprechen, Kontingente (externe Dienste gemockt)."""
import re

import numpy as np
import pytest

from app import audio
from studio import ai
from studio.accounts import create_user
from studio.models import AiUsage, StudioUser, StudioVoice

from .conftest import ADMIN, csrf_of, login


@pytest.fixture()
def fake_ai(monkeypatch):
    calls = {"script": [], "voice": []}

    async def scripts(**kw):
        calls["script"].append(kw)
        return ["Vorschlag eins.", "Vorschlag zwei.", "Vorschlag drei."]

    async def synth(voice_id, text, settings_=None):
        calls["voice"].append((voice_id, text, settings_))
        t = np.arange(48000) / 48000
        return audio.to_wav((np.sin(2 * np.pi * 300 * t) * 0.3).astype(np.float32))

    monkeypatch.setattr(ai.text_ai, "generate_scripts", scripts)
    monkeypatch.setattr(ai.audio, "synthesize", synth)
    monkeypatch.setattr(ai, "text_enabled", lambda: True)
    monkeypatch.setattr(ai, "voice_enabled", lambda: True)
    monkeypatch.setattr(ai, "account_voices", lambda force=False: [{"id": "acc123", "name": "Konto-Stimme", "info": "male"}])
    ai._hits.clear()
    return calls


def _voice(sdb, **kw):
    v = StudioVoice(name="Markus", elevenlabs_voice_id="abc123", description="warm", **kw)
    sdb.add(v)
    sdb.commit()
    return v


def h(client):
    return {"X-CSRF-Token": csrf_of(client, "/")}


def test_admin_releases_voice_from_account(sclient, sdb, fake_ai):
    login(sclient, *ADMIN)
    page = sclient.get("/admin/voices")
    assert "Konto-Stimme" in page.text
    res = sclient.post("/admin/voices", data={"account_voice_id": "acc123", "name": "", "description": "tief",
                                             "stability": "0.4", "similarity": "0.8", "style": "0", "speed": "1",
                                             "sort": "0", "csrf": csrf_of(sclient, "/admin/voices")}, follow_redirects=True)
    assert "freigegeben" in res.text
    v = sdb.query(StudioVoice).one()
    assert (v.name, v.elevenlabs_voice_id, v.stability) == ("Konto-Stimme", "acc123", 0.4)
    # bereits freigegebene Stimme wird nicht mehr zur Auswahl angeboten
    assert 'value="acc123">Konto-Stimme' not in sclient.get("/admin/voices").text
    bad = sclient.post("/admin/voices", data={"voice_id": "x/../y", "name": "X", "csrf": csrf_of(sclient, "/admin/voices")})
    assert bad.status_code == 400


def test_pro_cannot_manage_voices(sclient, sdb, fake_ai):
    create_user(sdb, "pro@example.com", "pro-passwort-1", "pro")
    login(sclient, "pro@example.com", "pro-passwort-1")
    assert sclient.get("/admin/voices").status_code == 403


def test_only_active_voices_are_listed(sclient, sdb, fake_ai):
    _voice(sdb)
    sdb.add(StudioVoice(name="Versteckt", elevenlabs_voice_id="zzz", active=False))
    sdb.commit()
    login(sclient, *ADMIN)
    st = sclient.get("/api/ai").json()
    assert [v["name"] for v in st["voices"]] == ["Markus"] and "elevenlabs_voice_id" not in st["voices"][0]
    assert st["text_enabled"] and st["voice_enabled"]


def test_script_suggestions(sclient, sdb, fake_ai):
    login(sclient, *ADMIN)
    res = sclient.post("/api/ai/script", json={"occasion": "Eröffnung", "botschaft": "Neues Geschäft",
                                               "seconds": 20, "tonality": "freundlich"}, headers=h(sclient))
    assert res.status_code == 200, res.text
    assert len(res.json()["scripts"]) == 3 and res.json()["usage"]["scripts"] == 1
    assert fake_ai["script"][0]["seconds"] == 20


def test_voice_creates_asset(sclient, sdb, fake_ai):
    v = _voice(sdb, stability=0.3)
    login(sclient, *ADMIN)
    res = sclient.post("/api/ai/voice", json={"voice_id": v.id, "text": "[excited] Jetzt neu bei uns!"},
                       headers=h(sclient))
    assert res.status_code == 201, res.text
    asset = res.json()["asset"]
    assert asset["origin"] == "ai" and asset["name"].startswith("Markus – Jetzt neu bei uns")
    assert abs(asset["duration"] - 1.0) < 0.01
    assert fake_ai["voice"][0][0] == "abc123" and fake_ai["voice"][0][2]["stability"] == 0.3
    assert [a["id"] for a in sclient.get("/api/assets").json()] == [asset["id"]]
    used = res.json()["usage"]["voice_chars"]
    assert used == ai.spoken_chars("[excited] Jetzt neu bei uns!") > 0


def test_voice_quota_and_inactive_voice(sclient, sdb, fake_ai):
    v = _voice(sdb)
    user = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    user.tts_chars_month = 10
    sdb.commit()
    login(sclient, *ADMIN)
    res = sclient.post("/api/ai/voice", json={"voice_id": v.id, "text": "Dieser Text ist zu lang"}, headers=h(sclient))
    assert res.status_code == 403 and "kontingent" in res.json()["detail"].lower()
    assert fake_ai["voice"] == []  # ElevenLabs wurde gar nicht aufgerufen
    v.active = False
    sdb.commit()
    assert sclient.post("/api/ai/voice", json={"voice_id": v.id, "text": "Hi"}, headers=h(sclient)).status_code == 404


def test_script_quota_and_rate_limit(sclient, sdb, fake_ai):
    login(sclient, *ADMIN)
    body = {"occasion": "A", "botschaft": "B"}
    for _ in range(ai.RATE["script"]):
        assert sclient.post("/api/ai/script", json=body, headers=h(sclient)).status_code == 200
    assert sclient.post("/api/ai/script", json=body, headers=h(sclient)).status_code == 429
    ai._hits.clear()
    user = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    user.scripts_month = ai.RATE["script"]
    sdb.commit()
    assert sclient.post("/api/ai/script", json=body, headers=h(sclient)).status_code == 403


def test_not_configured(sclient, sdb, monkeypatch):
    monkeypatch.setattr(ai, "text_enabled", lambda: False)
    monkeypatch.setattr(ai, "voice_enabled", lambda: False)
    v = _voice(sdb)
    login(sclient, *ADMIN)
    assert sclient.post("/api/ai/script", json={"occasion": "A", "botschaft": "B"}, headers=h(sclient)).status_code == 503
    assert sclient.post("/api/ai/voice", json={"voice_id": v.id, "text": "Hi"}, headers=h(sclient)).status_code == 503


def test_script_is_saved_with_project(sclient):
    login(sclient, *ADMIN)
    p = sclient.post("/api/projects", json={"name": "P"}, headers=h(sclient)).json()
    data = {**p["data"], "script": "[warmly] Hallo Welt"}
    assert sclient.put(f"/api/projects/{p['id']}", json={"name": "P", "data": data}, headers=h(sclient)).status_code == 200
    assert sclient.get(f"/api/projects/{p['id']}").json()["data"]["script"] == "[warmly] Hallo Welt"


def test_admin_sets_ai_quotas(sclient, sdb):
    user = create_user(sdb, "q@example.com", "quota-passwort", "pro")
    login(sclient, *ADMIN)
    sclient.post(f"/admin/users/{user.id}", data={"role": "pro", "active": "1", "quota_mb": "100", "export_limit": "",
                                                 "tts_chars_month": "5000", "scripts_month": "", "name": "",
                                                 "csrf": csrf_of(sclient, "/admin/users")})
    sdb.refresh(user)
    assert (user.tts_chars_month, user.scripts_month) == (5000, None)


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    """Bestehende studio.db aus Schritt 1/2 bekommt die neuen Spalten beim Start."""
    import sqlite3
    from sqlalchemy import create_engine, inspect
    from studio import database
    db = tmp_path / "alt.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE studio_users (id INTEGER PRIMARY KEY, email VARCHAR(254), name VARCHAR(120), "
                "password_hash VARCHAR(255), role VARCHAR(20), active BOOLEAN, session_epoch INTEGER, quota_mb INTEGER, "
                "export_limit INTEGER, libraries JSON, created_at DATETIME, last_login_at DATETIME)")
    con.execute("INSERT INTO studio_users (id, email, name, password_hash, role, active, session_epoch, quota_mb) "
                "VALUES (1, 'a@b.c', '', 'x', 'pro', 1, 0, 100)")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{db}")
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    cols = {c["name"] for c in inspect(engine).get_columns("studio_users")}
    assert {"tts_chars_month", "scripts_month"} <= cols
    assert "origin" in {c["name"] for c in inspect(engine).get_columns("studio_assets")}
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT tts_chars_month FROM studio_users").scalar() == 20000
