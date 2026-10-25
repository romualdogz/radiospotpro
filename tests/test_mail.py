import io
import re
import shutil
import wave

import numpy as np
import pytest

from app import audio, mailer
from app.models import QuoteRequest, SpotLength, Station, TimeSlot, Voice
from tests.smtp_sink import SmtpSink
from tests.conftest import PERIOD


def _tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * audio.SAMPLE_RATE)) / audio.SAMPLE_RATE
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture()
def sink(monkeypatch):
    s = SmtpSink()
    for key, value in {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(s.port), "SMTP_SECURITY": "none",
                       "SMTP_USER": "", "SMTP_FROM": "radiospot@onaircraft.test"}.items():
        monkeypatch.setenv(key, value)
    yield s
    s.close()


@pytest.fixture()
def request_row(client, db, monkeypatch):
    async def fake_synthesize(voice_id, text, settings_=None):
        return audio.to_wav(_tone(0.5 + len(text) / 100))

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    monkeypatch.setattr(audio, "synthesize", fake_synthesize)
    shutil.rmtree(audio.MEDIA_DIR / "cache", ignore_errors=True)
    db.add_all([Voice(name="Lena", elevenlabs_voice_id="abc"), Station(name="Radio A", price_per_second_cent=1000),
                TimeSlot(name="Tag"), SpotLength(seconds=20)])
    db.commit()
    r = client.post("/api/quote-requests", json={
        "configuration": {**PERIOD, "production": {"spot_length_id": 1, "voice_id": 1},
                          "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
        "brief": {"script": "Jetzt neu in Wien!"}, "customer_name": "Erika", "company": "Erikas Laden",
        "email": "erika@example.com", "street": "Gasse 1", "zip_code": "1010", "city": "Wien",
        "phone": "+43 1 1234", "accept_terms": True, "accept_privacy": True})
    assert r.status_code == 201
    page = client.get("/admin/login").text
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})
    return db.get(QuoteRequest, r.json()["id"])


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def test_send_pdf_and_audio(client, db, sink, request_row):
    rid = request_row.id
    page = client.get(f"/admin/requests/{rid}").text
    assert "Per E-Mail senden" in page and f"Radiospot-Anfrage Nr. {rid} – Erikas Laden" in page
    r = client.post(f"/admin/requests/{rid}/email", data={
        "csrf": _csrf(client, f"/admin/requests/{rid}"), "to": "studio@example.com, chef@example.com",
        "subject": "Spot für Erika", "body": "Hallo Studio,\r\nbitte schneiden.\r\n",
        "pdf": "on", "spot": "on", "voice": "on"})
    assert "E-Mail an studio@example.com, chef@example.com gesendet" in r.text
    assert "Bereits gesendet" in r.text

    [(rcpt, msg)] = sink.messages
    assert rcpt == ["studio@example.com", "chef@example.com"]
    assert msg["Subject"] == "Spot für Erika" and "radiospot@onaircraft.test" in msg["From"]
    assert msg.get_body(("plain",)).get_content().replace("\r\n", "\n") == "Hallo Studio,\nbitte schneiden.\n"
    files = {p.get_filename(): p for p in msg.iter_attachments()}
    assert list(files) == [f"onaircraft-anfrage-{rid}.pdf", f"onaircraft-spot-{rid}.wav", f"onaircraft-sprache-{rid}.wav"]
    assert files[f"onaircraft-anfrage-{rid}.pdf"].get_content().startswith(b"%PDF")
    with wave.open(io.BytesIO(files[f"onaircraft-spot-{rid}.wav"].get_content())) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 48_000, 3)

    db.refresh(request_row)
    [entry] = request_row.mail_log
    assert entry["to"] == ["studio@example.com", "chef@example.com"] and entry["by"] == "admin"
    assert len(entry["attachments"]) == 3


def test_validation_keeps_input(client, db, sink, request_row):
    rid = request_row.id
    token = _csrf(client, f"/admin/requests/{rid}")
    r = client.post(f"/admin/requests/{rid}/email", data={"csrf": token, "to": "kaputt@", "subject": "Betreff X",
                                                          "body": "Mein eigener Text", "pdf": "on"})
    assert "Ungültige E-Mail-Adresse: kaputt@" in r.text
    assert "Mein eigener Text" in r.text and 'value="Betreff X"' in r.text
    assert not sink.messages


def test_attachment_size_limit(client, db, sink, request_row, monkeypatch):
    monkeypatch.setattr(mailer, "MAX_ATTACHMENT_MB", 0.01)
    rid = request_row.id
    r = client.post(f"/admin/requests/{rid}/email", data={
        "csrf": _csrf(client, f"/admin/requests/{rid}"), "to": "a@example.com", "subject": "S", "body": "",
        "pdf": "on", "spot": "on"})
    assert "Bitte weniger Dateien auswählen" in r.text and not sink.messages


def test_auth_error_is_explained(monkeypatch):
    s = SmtpSink(auth=True, accept_auth=False)
    try:
        for key, value in {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(s.port), "SMTP_SECURITY": "none",
                           "SMTP_USER": "ich@example.com", "SMTP_PASSWORD": "falsch", "SMTP_FROM": ""}.items():
            monkeypatch.setenv(key, value)
        msg = mailer.build_message(["a@example.com"], "S", "B", [])
        assert "ich@example.com" in msg["From"]  # SMTP_FROM leer → Konto-Adresse
        with pytest.raises(mailer.MailError, match="App-Passwort"):
            mailer.send(msg)
    finally:
        s.close()


def test_not_configured(client, db, request_row, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    rid = request_row.id
    assert "E-Mail-Versand ist noch nicht eingerichtet" in client.get(f"/admin/requests/{rid}").text
    r = client.post(f"/admin/requests/{rid}/email", data={
        "csrf": _csrf(client, f"/admin/requests/{rid}"), "to": "a@example.com", "subject": "S", "body": ""})
    assert "nicht eingerichtet" in r.text


def test_default_recipient_from_settings(client, db, sink, request_row):
    token = _csrf(client, "/admin/settings")
    r = client.post("/admin/settings", data={"csrf": token, "mail_default_to": "kein-mail"})
    assert "gültige E-Mail-Adresse" in r.text
    client.post("/admin/settings", data={"csrf": token, "mail_default_to": "studio@onaircraft.at"})
    assert 'value="studio@onaircraft.at"' in client.get(f"/admin/requests/{request_row.id}").text


def test_parse_recipients():
    assert mailer.parse_recipients(" a@b.at; c@d.de  e@f.com ") == ["a@b.at", "c@d.de", "e@f.com"]
    with pytest.raises(mailer.MailError):
        mailer.parse_recipients("")
