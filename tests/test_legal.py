import re

from app.models import LegalText, QuoteRequest, SpotLength, Station, TimeSlot
from tests.conftest import PERIOD

BASE = {"configuration": {**PERIOD, "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
        "customer_name": "Erika", "email": "erika@example.com", "street": "Gasse 1", "zip_code": "1010",
        "city": "Wien", "phone": "+43 1 1234"}


def _setup(db):
    db.add_all([Station(name="Radio A", price_per_second_cent=1000), TimeSlot(name="Tag"), SpotLength(seconds=20)])
    db.commit()


def _login(client):
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})


def test_consent_required(client, db):
    _setup(db)
    r = client.post("/api/quote-requests", json={**BASE, "accept_terms": True})
    assert r.status_code == 422 and "Datenschutz" in str(r.json())
    r = client.post("/api/quote-requests", json={**BASE, "accept_privacy": True})
    assert r.status_code == 422 and "AGB" in str(r.json())
    assert db.query(QuoteRequest).count() == 0


def test_consent_is_recorded_with_version(client, db):
    _setup(db)
    agb = db.query(LegalText).filter_by(key="agb").one()
    r = client.post("/api/quote-requests", json={**BASE, "accept_terms": True, "accept_privacy": True})
    assert r.status_code == 201
    consent = db.query(QuoteRequest).one().consent
    assert set(consent) == {"agb", "datenschutz"}
    assert consent["agb"]["version"] == agb.version and consent["agb"]["accepted_at"]
    _login(client)
    assert f"Version {agb.version}" in client.get("/admin/requests/1").text


def test_legal_texts_public_and_editable(client, db):
    assert client.get("/api/legal/agb").json()["body"].startswith("PLATZHALTER")
    assert client.get("/api/legal/unbekannt").status_code == 404
    assert "Allgemeine Geschäftsbedingungen" in client.get("/agb").text
    _login(client)
    assert "Noch nicht hinterlegt" in client.get("/admin").text
    old_version = client.get("/api/legal/datenschutz").json()["version"]
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/legal").text).group(1)
    r = client.post("/admin/legal/datenschutz", data={"csrf": token, "title": "Datenschutzerklärung",
                    "body": "1. Verantwortlicher\r\nonaircraft <b>Wien</b>"}, follow_redirects=False)
    assert r.status_code == 303
    data = client.get("/api/legal/datenschutz").json()
    assert data["body"] == "1. Verantwortlicher\nonaircraft <b>Wien</b>" and data["version"] != old_version
    page = client.get("/datenschutz").text
    assert "&lt;b&gt;Wien&lt;/b&gt;" in page  # HTML wird nicht ausgeführt, nur angezeigt
