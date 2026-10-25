import re

from app.models import QuoteRequest, SpotLength, Station, TimeSlot

CONTACT = {"street": "Mariahilfer Straße 1", "zip_code": "1060", "city": "Wien", "phone": "+43 1 234567",
           "accept_terms": True, "accept_privacy": True}


def _setup(db):
    db.add_all([Station(name="Radio A", price_per_second_cent=1000),
                TimeSlot(name="Tag", price_factor_bp=10000), SpotLength(seconds=30)])
    db.commit()


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def _login(client):
    token = _csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token},
                    follow_redirects=False)
    assert r.status_code == 303


def test_catalog_and_quote(client, db):
    _setup(db)
    cat = client.get("/api/catalog").json()
    assert cat["stations"][0]["name"] == "Radio A"
    body = {"items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 2}]}
    r = client.post("/api/quote", json=body)
    assert r.status_code == 200
    assert r.json()["net_cent"] == 60000


def test_quote_request_recalculates_server_side(client, db):
    _setup(db)
    r = client.post("/api/quote-requests", json={
        "configuration": {"items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
        "customer_name": "Max", "email": "max@example.com", **CONTACT,
    })
    assert r.status_code == 201
    assert db.query(QuoteRequest).one().quote["net_cent"] == 30000


def test_admin_api_requires_auth(client, db):
    assert client.get("/api/admin/stations").status_code == 401
    r = client.get("/api/admin/stations", auth=("admin", "test-password"))
    assert r.status_code == 200
    r = client.post("/api/admin/stations", auth=("admin", "test-password"),
                    json={"name": "Neu", "price_per_second_cent": 700})
    assert r.status_code == 201 and r.json()["id"]


def test_admin_ui_requires_login(client, db):
    r = client.get("/admin/stations", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


def test_admin_ui_create_discount_with_euro_and_percent(client, db):
    _login(client)
    token = _csrf(client, "/admin/discounts/new")
    r = client.post("/admin/discounts/new", data={
        "csrf": token, "name": "Sommer", "kind": "percent", "value_raw": "12,5", "applies_to": "airtime",
        "min_spots": "20", "min_amount_cent": "1.000,00".replace(".", ""), "promo_code": "", "station_id": "",
        "valid_from": "", "valid_until": "", "stackable": "on", "active": "on", "sort_order": "0",
    }, follow_redirects=False)
    assert r.status_code == 303
    d = client.get("/api/admin/discounts").json()[0]
    assert d["value"] == 1250 and d["min_amount_cent"] == 100000 and d["min_spots"] == 20
    assert "12,5 %" in client.get("/admin/discounts").text


def test_admin_ui_rejects_missing_csrf(client, db):
    _login(client)
    r = client.post("/admin/stations/new", data={"name": "X", "price_per_second_cent": "1"})
    assert r.status_code == 400


def test_admin_ui_station_form_and_settings(client, db):
    _login(client)
    token = _csrf(client, "/admin/stations/new")
    client.post("/admin/stations/new", data={"csrf": token, "name": "Radio X", "kind": "radio", "ad_tax_applies": "on", "region": "",
                "price_per_second_cent": "8,50", "description": "", "sort_order": "1", "active": "on"})
    assert client.get("/api/admin/stations").json()[0]["price_per_second_cent"] == 850
    token = _csrf(client, "/admin/settings")
    client.post("/admin/settings", data={"csrf": token, "company_info": "onaircraft · Wien"})
    client.post("/admin/prices", data={"csrf": token, "ad_tax_rate": "5", "individual_booking": "on",
                "ad_tax_in_vat_base": "on", "min_order": "250", "currency": "eur", "studio_price": "349,00"})
    cfg = client.get("/api/admin/settings").json()
    assert cfg == {"company_info": "onaircraft · Wien",
                   "ad_tax_rate_bp": 500, "ad_tax_in_vat_base": True,
                   "min_order_cent": 25000, "studio_price_cent": 34900, "currency": "EUR",
                   "watermark_text": "Hörprobe von onaircraft", "watermark_interval_s": 7,
                   "master_lufs": -8.0, "master_ceiling_dbtp": -1.0, "individual_booking": True}
    for page in ["/admin", "/admin/time-slots", "/admin/spot-lengths", "/admin/addons", "/admin/requests"]:
        assert client.get(page).status_code == 200, page


def test_admin_ui_delete(client, db):
    _setup(db)
    _login(client)
    token = _csrf(client, "/admin/stations/1")
    r = client.post("/admin/stations/1/delete", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/admin/stations").json() == []


def _setup_production(db):
    from app.models import LanguageStyle, MusicStyle, Occasion, Tonality, Voice
    _setup(db)
    db.add_all([Voice(name="Lena"), MusicStyle(name="keine"), Occasion(name="Event"), Tonality(name="emotional"),
                LanguageStyle(name="Hochdeutsch", instruction="Neutral.")])
    db.commit()


def test_catalog_contains_production_options(client, db):
    _setup_production(db)
    cat = client.get("/api/catalog").json()
    assert cat["voices"][0]["name"] == "Lena"
    assert cat["studio_price_cent"] == 34900
    assert "instruction" not in cat["language_styles"][0]  # Prompt-Anweisungen bleiben intern
    assert cat["ai_enabled"] is False


def test_quote_request_with_brief(client, db):
    _setup_production(db)
    r = client.post("/api/quote-requests", json={
        "configuration": {"production": {"spot_length_id": 1, "voice_id": 1, "music_style_id": 1, "studio": True},
                          "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
        "brief": {"firma": "Aquaristik Neusiedl", "script": "Jetzt 20 % auf alles!"},
        "customer_name": "Erika", "email": "erika@example.com", **CONTACT,
    })
    assert r.status_code == 201
    assert r.json()["quote"]["net_cent"] == 34900 + 30000
    req = db.query(QuoteRequest).one()
    assert req.brief["firma"] == "Aquaristik Neusiedl"
    _login(client)
    page = client.get(f"/admin/requests/{req.id}").text
    assert "Aquaristik Neusiedl" in page and "Jetzt 20 % auf alles!" in page
    assert "Studiospot mit echtem Sprecher" in page


def test_generate_script_disabled_without_key(client, db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _setup_production(db)
    body = {"occasion_id": 1, "spot_length_id": 1, "tonality_id": 1, "language_style_id": 1,
            "firma": "X", "botschaft": "Y", "cta": "Z"}
    assert client.post("/api/generate-script", json=body).status_code == 503


def test_generate_script_success(client, db, monkeypatch):
    from app import ai
    _setup_production(db)
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return "Hallo Wien!"

    monkeypatch.setattr(ai, "generate_script", fake)
    body = {"occasion_id": 1, "spot_length_id": 1, "tonality_id": 1, "language_style_id": 1,
            "firma": "X", "botschaft": "Y", "cta": "Z"}
    r = client.post("/api/generate-script", json=body)
    assert r.status_code == 200 and r.json() == {"script": "Hallo Wien!"}
    assert seen["seconds"] == 30 and seen["style_instruction"] == "Neutral."


def test_admin_pages_for_production_entities(client, db):
    _setup_production(db)
    _login(client)
    for slug in ["voices", "music-styles", "occasions", "tonalities", "language-styles", "spot-lengths"]:
        assert client.get(f"/admin/{slug}").status_code == 200, slug
        assert client.get(f"/admin/{slug}/new").status_code == 200, slug
    token = _csrf(client, "/admin/voices/new")
    r = client.post("/admin/voices/new", data={"csrf": token, "name": "Max", "tag": "", "tier": "Demo",
                    "sample_url": "", "pitch_bp": "1", "rate_bp": "1,1",
                    "sort_order": "2", "active": "on"}, follow_redirects=False)
    assert r.status_code == 303
    v = client.get("/api/admin/voices", auth=("admin", "test-password")).json()[-1]
    assert v["name"] == "Max" and v["rate_bp"] == 11000



def _create_request(client, db, country="AT", vat_id=None):
    _setup_production(db)
    r = client.post("/api/quote-requests", json={
        "configuration": {"production": {"spot_length_id": 1, "voice_id": 1, "music_style_id": 1, "studio": True},
                          "items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 3}],
                          "country": country, "vat_id": vat_id},
        "brief": {"firma": "Aquaristik Neusiedl", "occasion": "Event", "script": "Größte Auswahl – jetzt!"},
        "customer_name": "Erika Müller", "email": "erika@example.com", **CONTACT,
    })
    assert r.status_code == 201
    return r.json()


def test_customer_pdf_link_is_signed(client, db):
    data = _create_request(client, db)
    assert data["quote"]["vat_rate_bp"] == 2000
    r = client.get(data["pdf_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    # ohne / mit falschem Token kein Zugriff, auch nicht auf andere Anfragen
    assert client.get(f"/api/quote-requests/{data['id']}/pdf?token=falsch").status_code == 404
    token = data["pdf_url"].split("token=")[1]
    assert client.get(f"/api/quote-requests/{data['id'] + 1}/pdf?token={token}").status_code == 404


def test_admin_pdf_and_content(client, db):
    from pypdf import PdfReader
    import io
    data = _create_request(client, db, country="DE")
    assert client.get(f"/admin/requests/{data['id']}/pdf", follow_redirects=False).status_code == 303
    _login(client)
    r = client.get(f"/admin/requests/{data['id']}/pdf")
    assert r.status_code == 200
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(r.content)).pages)
    for expected in ["Anfrage Nr. 1", "Erika Müller", "Aquaristik Neusiedl", "Studiospot mit echtem Sprecher",
                     "MwSt. 19 % (Deutschland)", "Größte Auswahl", "349,00 €"]:
        assert expected in text, expected



def test_pdf_reverse_charge(client, db):
    from pypdf import PdfReader
    import io
    data = _create_request(client, db, country="DE", vat_id="DE123456789")
    assert data["quote"]["reverse_charge"] is True and data["quote"]["vat_cent"] == 0
    text = PdfReader(io.BytesIO(client.get(data["pdf_url"]).content)).pages[0].extract_text()
    assert "DE123456789" in text and "Nettorechnung" in text and "Reverse Charge" in text
    _login(client)
    assert "Nettorechnung" in client.get(f"/admin/requests/{data['id']}").text



def test_request_requires_booking(client, db):
    _setup_production(db)
    r = client.post("/api/quote-requests", json={
        "configuration": {"production": {"spot_length_id": 1, "voice_id": 1, "studio": True}},
        "customer_name": "Erika", "email": "erika@example.com", **CONTACT,
    })
    assert r.status_code == 422 and "Sender oder Stream" in r.json()["detail"]


def test_catalog_station_kind(client, db):
    _setup(db)
    db.add(Station(name="Energy Streams", kind="stream", ad_tax_applies=False, price_per_second_cent=300))
    db.commit()
    kinds = {s["name"]: s["kind"] for s in client.get("/api/catalog").json()["stations"]}
    assert kinds == {"Radio A": "radio", "Energy Streams": "stream"}



def test_request_requires_address_and_phone(client, db):
    _setup(db)
    base = {"configuration": {"items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}]},
            "customer_name": "Erika", "email": "erika@example.com", **CONTACT}
    for missing in ["street", "zip_code", "city", "phone"]:
        r = client.post("/api/quote-requests", json={**base, missing: "  "})
        assert r.status_code == 422, missing
    assert client.post("/api/quote-requests", json=base).status_code == 201


def test_address_in_admin_and_pdf(client, db):
    from pypdf import PdfReader
    import io
    data = _create_request(client, db)
    text = PdfReader(io.BytesIO(client.get(data["pdf_url"]).content)).pages[0].extract_text()
    assert "Mariahilfer Straße 1" in text and "1060 Wien" in text and "+43 1 234567" in text
    _login(client)
    page = client.get(f"/admin/requests/{data['id']}").text
    assert "Mariahilfer Straße 1" in page and "1060 Wien" in page



def test_catalog_countries_without_vat(client, db):
    countries = client.get("/api/catalog").json()["countries"]
    assert countries[0] == {"code": "AT", "name": "Österreich", "reverse_charge": False}
    assert {"code": "CH", "name": "Schweiz", "reverse_charge": True} in countries
    assert all("vat_rate_bp" not in c for c in countries)  # MwSt. erscheint erst auf Kostenaufstellung/Rechnung


def test_admin_country_crud_and_vat(client, db):
    _setup(db)
    _login(client)
    token = _csrf(client, "/admin/countries/new")
    r = client.post("/admin/countries/new", data={"csrf": token, "name": "Norwegen", "code": "no",
                    "vat_rate_bp": "0", "sort_order": "99", "active": "on"}, follow_redirects=False)
    assert r.status_code == 303
    assert {"code": "NO", "name": "Norwegen", "reverse_charge": False} in client.get("/api/catalog").json()["countries"]
    body = {"items": [{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}], "country": "NO"}
    assert client.post("/api/quote", json=body).json()["vat_cent"] == 0
