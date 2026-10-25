from datetime import date

import pytest

from app.models import AddOn, Discount, DiscountKind, DiscountScope, SpotLength, Station, TimeSlot
from app.pricing import QuoteError, calculate_quote
from app.schemas import QuoteIn
from app.settings_store import save_settings


@pytest.fixture()
def catalog(db):
    st1 = Station(name="Radio A", price_per_second_cent=1000)   # 10 €/s
    st2 = Station(name="Radio B", price_per_second_cent=500)    # 5 €/s
    slot = TimeSlot(name="Morning", price_factor_bp=15000)      # ×1,5
    length = SpotLength(seconds=20)
    addon = AddOn(name="Produktion", price_cent=30000)          # 300 €
    db.add_all([st1, st2, slot, length, addon])
    db.commit()
    return {"st1": st1, "st2": st2, "slot": slot, "len": length, "addon": addon}


def q(c, spots=10, station="st1", addon=False, promo=None, country="DE", vat_id=None):
    return QuoteIn(
        country=country, vat_id=vat_id,
        items=[{"station_id": c[station].id, "time_slot_id": c["slot"].id,
                "spot_length_id": c["len"].id, "spots": spots}],
        addon_ids=[c["addon"].id] if addon else [],
        promo_code=promo,
    )


def test_base_price(db, catalog):
    r = calculate_quote(db, q(catalog, spots=10, addon=True))
    # 20 s × 10 € × 1,5 = 300 € pro Spot × 10 = 3.000 € + 300 € Produktion
    assert r.lines[0].unit_price_cent == 30000
    assert r.airtime_subtotal_cent == 300000
    assert r.subtotal_cent == 330000
    assert r.net_cent == 330000
    # Werbeabgabe 5 % nur auf die Sendezeit: 3.000 € → 150 €
    assert r.ad_tax_base_cent == 300000
    assert r.ad_tax_cent == 15000
    # MwSt. auf Netto + Werbeabgabe: 19 % von 3.450 € = 655,50 €
    assert r.vat_base_cent == 345000
    assert r.vat_cent == 65550
    assert r.gross_cent == 330000 + 15000 + 65550


def test_ad_tax_after_discounts(db, catalog):
    db.add_all([
        Discount(name="10 % Sendezeit", kind=DiscountKind.percent, value=1000),
        # 330 € auf den Gesamtbetrag → anteilig 300 € Sendezeit, 30 € Produktion
        Discount(name="Fix gesamt", kind=DiscountKind.fixed, value=33000, applies_to=DiscountScope.total),
    ])
    db.commit()
    r = calculate_quote(db, q(catalog, addon=True))
    assert r.discount_total_cent == 30000 + 33000
    # Sendezeit 3.000 € − 300 € − 300 € anteilig = 2.400 €
    assert r.ad_tax_base_cent == 240000
    assert r.ad_tax_cent == 12000


def test_ad_tax_configurable(db, catalog):
    save_settings(db, {"ad_tax_rate_bp": 0})
    r = calculate_quote(db, q(catalog))
    assert r.ad_tax_cent == 0 and r.gross_cent == 357000

    save_settings(db, {"ad_tax_rate_bp": 500, "ad_tax_in_vat_base": False})
    r = calculate_quote(db, q(catalog))
    assert r.ad_tax_cent == 15000
    assert r.vat_cent == 57000  # 19 % nur auf 3.000 €


def test_volume_discount_only_on_airtime(db, catalog):
    db.add(Discount(name="10 %", kind=DiscountKind.percent, value=1000, min_spots=10))
    db.commit()
    r = calculate_quote(db, q(catalog, spots=10, addon=True))
    assert r.discount_total_cent == 30000  # 10 % von 3.000 €, nicht von 3.300 €
    assert calculate_quote(db, q(catalog, spots=9)).discounts == []


def test_stackable_discounts_add_up(db, catalog):
    db.add_all([
        Discount(name="A", kind=DiscountKind.percent, value=500),
        Discount(name="B", kind=DiscountKind.fixed, value=10000, applies_to=DiscountScope.total),
    ])
    db.commit()
    r = calculate_quote(db, q(catalog))
    assert r.discount_total_cent == 15000 + 10000


def test_exclusive_wins_only_if_better(db, catalog):
    db.add_all([
        Discount(name="A", kind=DiscountKind.percent, value=500),
        Discount(name="B", kind=DiscountKind.percent, value=500),
        Discount(name="Exklusiv", kind=DiscountKind.percent, value=800, stackable=False),
    ])
    db.commit()
    r = calculate_quote(db, q(catalog))
    assert [d.name for d in r.discounts] == ["A", "B"]  # 10 % > 8 %

    db.query(Discount).filter_by(name="Exklusiv").one().value = 1500
    db.commit()
    r = calculate_quote(db, q(catalog))
    assert [d.name for d in r.discounts] == ["Exklusiv"]


def test_promo_code(db, catalog):
    db.add(Discount(name="Code", kind=DiscountKind.fixed, value=5000, promo_code="RADIO"))
    db.commit()
    assert calculate_quote(db, q(catalog)).discount_total_cent == 0
    r = calculate_quote(db, q(catalog, promo=" radio "))
    assert r.discount_total_cent == 5000 and r.promo_code_status == "applied"
    assert calculate_quote(db, q(catalog, promo="FALSCH")).promo_code_status == "invalid"


def test_validity_window(db, catalog):
    db.add(Discount(name="Aktion", kind=DiscountKind.percent, value=1000,
                    valid_from=date(2026, 11, 1), valid_until=date(2026, 11, 30)))
    db.commit()
    assert calculate_quote(db, q(catalog), today=date(2026, 10, 31)).discounts == []
    assert calculate_quote(db, q(catalog), today=date(2026, 11, 15)).discount_total_cent == 30000


def test_station_specific_discount(db, catalog):
    db.add(Discount(name="Nur B", kind=DiscountKind.percent, value=1000, station_id=catalog["st2"].id))
    db.commit()
    assert calculate_quote(db, q(catalog, station="st1")).discounts == []
    r = calculate_quote(db, q(catalog, station="st2"))  # 20 × 5 € × 1,5 × 10 = 1.500 €
    assert r.discount_total_cent == 15000


def test_discount_never_exceeds_subtotal(db, catalog):
    db.add(Discount(name="Riesig", kind=DiscountKind.fixed, value=10_000_000))
    db.commit()
    r = calculate_quote(db, q(catalog))
    assert r.net_cent == 0 and r.gross_cent == 0


def test_inactive_product_rejected(db, catalog):
    catalog["st1"].active = False
    db.commit()
    with pytest.raises(QuoteError):
        calculate_quote(db, q(catalog))


@pytest.fixture()
def production(db, catalog):
    from app.models import MusicStyle, Voice
    v, m = Voice(name="Lena"), MusicStyle(name="Corporate")
    db.add_all([v, m])
    db.commit()
    return {**catalog, "lena": v, "music": m}


def prod_q(c, studio=False, airtime=False, promo=None, country="DE"):
    return QuoteIn(
        country=country,
        production={"spot_length_id": c["len"].id, "voice_id": c["lena"].id,
                    "music_style_id": c["music"].id, "studio": studio},
        items=[{"station_id": c["st1"].id, "time_slot_id": c["slot"].id,
                "spot_length_id": c["len"].id, "spots": 10}] if airtime else [],
        promo_code=promo,
    )


def test_text_and_demo_are_free(db, production):
    r = calculate_quote(db, prod_q(production))
    assert r.production.studio is False
    assert r.production.total_cent == 0 and r.gross_cent == 0


def test_studio_spot_flat_price(db, production):
    r = calculate_quote(db, prod_q(production, studio=True))
    assert r.production.total_cent == 34900
    assert r.ad_tax_cent == 0  # Produktion ist keine Werbeleistung
    assert r.vat_cent == 6631  # 19 % von 349 €

    save_settings(db, {"studio_price_cent": 29900})
    assert calculate_quote(db, prod_q(production, studio=True)).production.total_cent == 29900


def test_studio_discount_and_ad_tax_only_on_airtime(db, production):
    db.add(Discount(name="10 % Studiospot", kind=DiscountKind.percent, value=1000,
                    applies_to=DiscountScope.production, promo_code="WILLKOMMEN"))
    db.commit()
    r = calculate_quote(db, prod_q(production, studio=True, airtime=True, promo="willkommen"))
    assert r.discount_total_cent == 3490            # 10 % von 349 €
    assert r.ad_tax_base_cent == 300000             # Sendezeit unberührt
    assert r.ad_tax_cent == 15000


def test_quote_needs_production_or_items():
    with pytest.raises(ValueError):
        QuoteIn(items=[])


def test_vat_by_country(db, catalog):
    at = calculate_quote(db, q(catalog, country="AT"))
    de = calculate_quote(db, q(catalog, country="DE"))
    # Netto 3.000 € + 150 € Werbeabgabe = 3.150 € MwSt.-Basis
    assert at.vat_rate_bp == 2000 and at.vat_cent == 63000 and at.country_name == "Österreich"
    assert de.vat_rate_bp == 1900 and de.vat_cent == 59850 and de.country_name == "Deutschland"
    from app.models import Country
    db.query(Country).filter_by(code="AT").one().vat_rate_bp = 1000
    db.commit()
    assert calculate_quote(db, q(catalog, country="AT")).vat_cent == 31500


def test_unknown_country_rejected(db, catalog):
    with pytest.raises(QuoteError, match="Rechnungsland"):
        calculate_quote(db, q(catalog, country="XX"))
    with pytest.raises(ValueError):
        QuoteIn(items=[{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}], country="Austria")


def test_other_countries_use_their_settings(db, catalog):
    ch = calculate_quote(db, q(catalog, country="CH"))
    assert ch.country_name == "Schweiz" and ch.vat_rate_bp == 2000
    ch_b2b = calculate_quote(db, q(catalog, country="CH", vat_id="CHE-123.456.789 MWST"))
    assert ch_b2b.reverse_charge and ch_b2b.vat_cent == 0
    # Österreich: auch mit UID keine Nettorechnung
    assert not calculate_quote(db, q(catalog, country="AT", vat_id="ATU12345678")).reverse_charge
    it = calculate_quote(db, q(catalog, country="IT", vat_id="IT12345678901"))
    assert it.reverse_charge


def test_germany_with_vat_id_is_net_invoice(db, catalog):
    base = dict(items=[{"station_id": catalog["st1"].id, "time_slot_id": catalog["slot"].id,
                        "spot_length_id": catalog["len"].id, "spots": 10}])
    r = calculate_quote(db, QuoteIn(**base, country="DE", vat_id="de 123 456 789"))
    assert r.reverse_charge and r.vat_id == "DE123456789"
    assert r.vat_cent == 0 and r.gross_cent == r.net_cent + r.ad_tax_cent
    # Österreich mit UID: normale 20 %
    r = calculate_quote(db, QuoteIn(**base, country="AT", vat_id="ATU12345678"))
    assert not r.reverse_charge and r.vat_rate_bp == 2000
    # Deutschland ohne UID: 19 %
    assert calculate_quote(db, QuoteIn(**base, country="DE")).vat_rate_bp == 1900


@pytest.mark.parametrize("country,vat_id", [("DE", "DE12345"), ("DE", "ATU12345678"), ("AT", "DE123456789")])
def test_invalid_vat_id_rejected(country, vat_id):
    with pytest.raises(ValueError, match="UID-Nummer ungültig"):
        QuoteIn(items=[{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1, "spots": 1}],
                country=country, vat_id=vat_id)


def test_addon_requires_studio(db, production):
    express = AddOn(name="Express-Produktion", price_cent=4900, requires_studio=True)
    db.add(express)
    db.commit()
    with pytest.raises(QuoteError, match="Nur zusammen mit dem Studiospot"):
        calculate_quote(db, QuoteIn(**{**prod_q(production).model_dump(), "addon_ids": [express.id]}))
    r = calculate_quote(db, QuoteIn(**{**prod_q(production, studio=True).model_dump(), "addon_ids": [express.id]}))
    assert r.net_cent == 34900 + 4900



def test_streams_without_ad_tax(db, catalog):
    stream = Station(name="Energy Streams", kind="stream", ad_tax_applies=False, price_per_second_cent=1000)
    db.add(stream)
    db.add(Discount(name="10 % Sendezeit", kind=DiscountKind.percent, value=1000))
    db.commit()
    item = lambda st: {"station_id": st.id, "time_slot_id": catalog["slot"].id,
                       "spot_length_id": catalog["len"].id, "spots": 10}
    r = calculate_quote(db, QuoteIn(items=[item(catalog["st1"]), item(stream)]))
    # je 3.000 € Radio und Stream; 10 % Rabatt anteilig → Werbeabgabe nur auf 2.700 € Radio
    assert r.lines[1].kind == "stream"
    assert r.ad_tax_base_cent == 270000 and r.ad_tax_cent == 13500
    assert calculate_quote(db, QuoteIn(items=[item(stream)])).ad_tax_cent == 0
