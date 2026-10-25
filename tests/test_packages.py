import re

import pytest

from app.models import AddOn, Discount, DiscountKind, DiscountScope, MusicStyle, Package, SpotLength, Station, TimeSlot, Voice
from app.pricing import QuoteError, calculate_quote
from app.schemas import QuoteIn


@pytest.fixture()
def cat(db):
    objs = {
        "len20": SpotLength(seconds=20), "len30": SpotLength(seconds=30), "voice": Voice(name="Lena"),
        "music": MusicStyle(name="keine"), "station": Station(name="Radio A", price_per_second_cent=1000),
        "slot": TimeSlot(name="Tag", price_factor_bp=10000),
        "express": AddOn(name="Express", price_cent=4900, requires_studio=True),
        "basic": Package(name="Basic", price_cent=100000, spots=40, max_seconds=20),
        "allin": Package(name="All-in", price_cent=300000, airtime_cent=265100, spots=80, includes_studio=True),
        "stream": Package(name="Streams", price_cent=50000, ad_tax_applies=False),
    }
    db.add_all(objs.values())
    db.commit()
    return objs


def pq(c, package, length="len20", studio=False, addons=(), items=False, promo=None):
    return QuoteIn(
        country="AT", package_id=c[package].id, promo_code=promo,
        production={"spot_length_id": c[length].id, "voice_id": c["voice"].id, "studio": studio},
        addon_ids=[c[a].id for a in addons],
        items=[{"station_id": c["station"].id, "time_slot_id": c["slot"].id, "spot_length_id": c[length].id,
                "spots": 10}] if items else [],
    )


def test_flat_price_with_ad_tax_and_vat(db, cat):
    r = calculate_quote(db, pq(cat, "basic"))
    assert r.package.name == "Basic" and r.package_subtotal_cent == 100000
    assert r.net_cent == 100000 and r.total_spots == 40
    assert r.ad_tax_base_cent == 100000 and r.ad_tax_cent == 5000   # 5 % auf den ganzen Paketpreis
    assert r.vat_cent == 21000                                     # 20 % von 1.050 €
    assert r.production.total_cent == 0


def test_studio_included(db, cat):
    r = calculate_quote(db, pq(cat, "allin", studio=True, addons=["express"]))
    assert r.production.studio and r.production.in_package and r.production.total_cent == 0
    assert r.net_cent == 300000 + 4900
    assert r.ad_tax_base_cent == 265100  # nur der Sendezeit-Anteil
    with pytest.raises(QuoteError, match="Studiospot"):
        calculate_quote(db, pq(cat, "basic", addons=["express"]))


def test_stream_package_without_ad_tax(db, cat):
    assert calculate_quote(db, pq(cat, "stream")).ad_tax_cent == 0


def test_max_seconds_and_inactive(db, cat):
    with pytest.raises(QuoteError, match="bis 20 Sek"):
        calculate_quote(db, pq(cat, "basic", length="len30"))
    cat["basic"].active = False
    db.commit()
    with pytest.raises(QuoteError, match="Komplettpaket"):
        calculate_quote(db, pq(cat, "basic"))


def test_discounts_on_packages(db, cat):
    db.add_all([
        Discount(name="Sendezeit 10 %", kind=DiscountKind.percent, value=1000, applies_to=DiscountScope.airtime),
        Discount(name="Code 5 %", kind=DiscountKind.percent, value=500, applies_to=DiscountScope.total, promo_code="PAKET"),
    ])
    db.commit()
    r = calculate_quote(db, pq(cat, "basic", promo="paket"))
    assert [d.name for d in r.discounts] == ["Code 5 %"]   # Sendezeit-Rabatt gilt nicht fürs Paket
    assert r.net_cent == 95000 and r.ad_tax_base_cent == 95000
    r = calculate_quote(db, pq(cat, "basic", items=True))  # Paket + Einzelbuchung
    assert r.lines and r.discounts[0].amount_cent == 20000  # 10 % nur auf 2.000 € Einzelbuchung
    assert r.ad_tax_base_cent == 100000 + 180000


def test_package_only_quote_is_valid():
    QuoteIn(package_id=1)


def test_catalog_lists_active_packages_and_request_pdf(client, db, cat):
    names = [p["name"] for p in client.get("/api/catalog").json()["packages"]]
    assert names == ["Basic", "All-in", "Streams"]
    r = client.post("/api/quote-requests", json={
        "configuration": pq(cat, "allin", studio=True).model_dump(),
        "customer_name": "Max", "email": "max@example.com", "street": "Gasse 1", "zip_code": "1010",
        "city": "Wien", "phone": "+43 1 234567", "accept_terms": True, "accept_privacy": True})
    assert r.status_code == 201, r.text
    assert r.json()["quote"]["package"]["name"] == "All-in"
    pdf = client.get(r.json()["pdf_url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_admin_form_and_sales_access(client, db):
    def csrf(path):
        return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)
    token = csrf("/admin/login")
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})
    token = csrf("/admin/packages/new")
    r = client.post("/admin/packages/new", data={
        "csrf": token, "name": "Sommer", "badge": "Neu", "price_cent": "1.990,00", "description": "60 Spots",
        "spots": "60", "max_seconds": "0", "includes_studio": "on", "ad_tax_applies": "on",
        "airtime_cent": "1641", "sort_order": "1", "active": "on"})
    assert "gespeichert" in r.text, re.findall(r'class="error">([^<]*)', r.text)
    p = db.query(Package).filter_by(name="Sommer").one()
    assert p.price_cent == 199000 and p.airtime_cent == 164100 and p.includes_studio
    r = client.post("/admin/packages/new", data={"csrf": token, "name": "Falsch", "price_cent": "100",
                                                  "airtime_cent": "200", "spots": "0", "max_seconds": "0"})
    assert "nicht höher als der Paketpreis" in r.text
    from app.routers.admin_ui import SALES_SECTIONS
    assert "packages" in SALES_SECTIONS


def test_example_packages_created_once_inactive(db):
    from app.seed import ensure_example_packages
    ensure_example_packages(db)
    assert db.query(Package).count() == 3
    assert not any(p.active for p in db.query(Package))
    db.query(Package).delete()
    db.commit()
    ensure_example_packages(db)  # gelöschte Beispiele kommen nicht zurück
    assert db.query(Package).count() == 0


def test_package_with_station_choice(client, db, cat):
    from app.models import CoverageArea
    area = CoverageArea(name="UKW Wien", technology="ukw", states=["wien"])
    db.add(area)
    db.flush()
    nostalgie = Station(name="Radio Nostalgie", price_per_second_cent=700, coverage_ids=[area.id], map_color="#0057b8")
    db.add(nostalgie)
    db.flush()
    cat["basic"].station_ids = [cat["station"].id, nostalgie.id]
    db.commit()

    with pytest.raises(QuoteError, match="einen Sender wählen"):
        calculate_quote(db, pq(cat, "basic"))
    data = pq(cat, "basic").model_copy(update={"package_station_id": nostalgie.id})
    r = calculate_quote(db, data)
    assert r.package.station == "Radio Nostalgie" and r.package.coverage == "UKW Wien"
    assert r.net_cent == 100000  # Pauschalpreis unabhängig vom Sender
    with pytest.raises(QuoteError):  # Sender gehört nicht zum Paket
        calculate_quote(db, pq(cat, "basic").model_copy(update={"package_station_id": 999}))
    # Pakete ohne Senderwahl bleiben wie bisher
    assert calculate_quote(db, pq(cat, "allin")).package.station == ""

    assert client.get("/api/catalog").json()["packages"][0]["station_ids"] == [cat["station"].id, nostalgie.id]
    req = client.post("/api/quote-requests", json={
        "configuration": data.model_dump(), "customer_name": "Max", "email": "max@example.com",
        "street": "Gasse 1", "zip_code": "1010", "city": "Wien", "phone": "+43 1 234567",
        "accept_terms": True, "accept_privacy": True}).json()
    assert req["quote"]["package"]["station"] == "Radio Nostalgie"
    pdf = client.get(req["pdf_url"]).content
    from io import BytesIO
    from pypdf import PdfReader
    assert "Sender: Radio Nostalgie" in PdfReader(BytesIO(pdf)).pages[0].extract_text()


def test_admin_package_station_field(client, db, cat):
    def csrf(path):
        return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)
    token = csrf("/admin/login")
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})
    page = client.get(f"/admin/packages/{cat['basic'].id}").text
    assert "Wählbare Sender" in page and 'name="station_ids"' in page
    token = csrf("/admin/packages/new")
    r = client.post("/admin/packages/new", data={
        "csrf": token, "name": "Wahl", "price_cent": "990", "spots": "20", "max_seconds": "0", "airtime_cent": "0",
        "station_ids": [str(cat["station"].id)], "ad_tax_applies": "on", "sort_order": "9", "active": "on"})
    assert "gespeichert" in r.text
    assert db.query(Package).filter_by(name="Wahl").one().station_ids == [cat["station"].id]


def test_package_coverage_wins_and_dashboard_hint(client, db, cat):
    from app.models import CoverageArea
    dab = CoverageArea(name="DAB+ National", technology="dab", states=["wien"])
    db.add(dab)
    db.flush()
    nostalgie = Station(name="Radio Nostalgie", price_per_second_cent=700, map_color="#0057b8")  # ohne Gebiete
    db.add(nostalgie)
    db.flush()
    cat["basic"].station_ids = [nostalgie.id]
    db.commit()
    data = pq(cat, "basic").model_copy(update={"package_station_id": nostalgie.id})
    assert calculate_quote(db, data).package.coverage == ""

    def csrf(path):
        return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)
    token = csrf("/admin/login")
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})
    page = client.get("/admin").text
    assert "Ohne Sendegebiet" in page and "Sender „Radio Nostalgie“" in page and "Paket „Basic“" in page

    cat["basic"].coverage_ids = [dab.id]  # Gebiet am Paket → gilt auch mit Senderwahl
    db.commit()
    assert calculate_quote(db, data).package.coverage == "DAB+ National"
    assert "Paket „Basic“" not in client.get("/admin").text
