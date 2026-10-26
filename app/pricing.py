"""Preisberechnung des Radiospot-Konfigurators.

Spot:
    Text (auch per KI) und Hörbeispiel sind gratis.
    Studiospot mit echtem Sprecher = Pauschalpreis aus den Einstellungen (Standard 349 € netto)

Komplettpaket (optional):
    Pauschalpreis netto; kann den Studiospot enthalten (dann 0 € für den Studiospot).
    Rabatte „auf den Gesamtbetrag“ (z. B. Gutscheincodes) gelten auch für Pakete, Rabatte nur auf
    Sendezeit bzw. einen Sender nicht. Werbeabgabe auf den hinterlegten Sendezeit-Anteil des Pakets.

Schaltung (optional) je Position:
    Stückpreis = Spotlänge (s) × Sekundenpreis des Senders × Faktor der Zeitschiene
    Positionspreis = Stückpreis × Anzahl Ausstrahlungen

Rabattlogik:
    * Alle aktiven Rabatte, deren Bedingungen erfüllt sind, sind "anwendbar".
    * Kombinierbare Rabatte (stackable) werden addiert – jeweils auf die ursprüngliche Basis
      gerechnet, nicht verkettet. Das ist für Kunden nachvollziehbar.
    * Exklusive Rabatte (nicht stackable) werden nie kombiniert. Der beste exklusive Rabatt
      gewinnt nur, wenn er höher ist als die Summe aller kombinierbaren Rabatte.
    * Der Gesamtrabatt kann die Zwischensumme nie übersteigen.

Werbeabgabe:
    * Satz im Admin einstellbar (Standard 5 %, 0 = deaktiviert).
    * Bemessungsgrundlage ist das Werbeentgelt = Sendezeit nach Rabatten. Zusatzleistungen
      (z. B. Spotproduktion) sind keine Werbeleistung und bleiben außen vor. Rabatte auf den
      Gesamtbetrag werden anteilig auf Sendezeit und Zusatzleistungen aufgeteilt.
    * Die Werbeabgabe ist Teil der Bemessungsgrundlage für die Umsatzsteuer
      (abschaltbar über die Einstellung "Werbeabgabe in MwSt.-Basis").
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from .models import AddOn, Country, CoverageArea, Package, Discount, DiscountKind, DiscountScope, MusicStyle, SpotLength, Station, TimeSlot, Voice
from .schemas import AppliedDiscount, QuoteAddOn, QuoteIn, QuoteLine, QuoteOut, QuotePackage, QuoteProduction
from .settings_store import get_settings
from . import wheel


class QuoteError(ValueError):
    """Ungültige Konfiguration (z. B. inaktives oder unbekanntes Produkt)."""


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _bp(amount_cent: int, basis_points: int) -> int:
    return _round(Decimal(amount_cent) * basis_points / 10_000)


@dataclass
class _Line:
    station_id: int
    total_cent: int
    ad_tax_applies: bool


def _load_active(db: Session, model, ids: set[int], label: str) -> dict:
    if not ids:
        return {}
    rows = db.query(model).filter(model.id.in_(ids), model.active.is_(True)).all()
    found = {r.id: r for r in rows}
    missing = ids - found.keys()
    if missing:
        raise QuoteError(f"{label} nicht verfügbar: {sorted(missing)}")
    return found


def _discount_base(d: Discount, lines: list[_Line], airtime: int, production: int, addons: int,
                   package: int = 0) -> int:
    if d.station_id is not None:
        # Senderbezogene Rabatte gelten nur für die Sendezeit dieses Senders.
        return sum(l.total_cent for l in lines if l.station_id == d.station_id)
    if d.applies_to == DiscountScope.airtime:
        return airtime
    if d.applies_to == DiscountScope.production:
        return production
    return airtime + production + addons + package


def _is_eligible(d: Discount, *, today: date, total_spots: int, base: int, promo_code: str | None) -> bool:
    if d.valid_from and today < d.valid_from:
        return False
    if d.valid_until and today > d.valid_until:
        return False
    if total_spots < d.min_spots:
        return False
    if base <= 0 or base < d.min_amount_cent:
        return False
    if d.promo_code:
        return promo_code is not None and promo_code.strip().lower() == d.promo_code.strip().lower()
    return True


def _discount_amount(d: Discount, base: int) -> int:
    amount = _bp(base, d.value) if d.kind == DiscountKind.percent else d.value
    return min(amount, base)


MAX_ADVANCE_DAYS = 730   # Beginn höchstens zwei Jahre im Voraus
MAX_PERIOD_DAYS = 366


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def booking_period(data: QuoteIn, package, lead_days: int, today: date) -> tuple[date, date, int] | None:
    """Kampagnenzeitraum prüfen: Vorlaufzeit, Ende ≥ Beginn; bei Paketen mit Laufzeit wird das Ende berechnet."""
    if data.start_date is None:
        return None
    start = data.start_date
    earliest = today + timedelta(days=lead_days)
    if start < earliest:
        raise QuoteError(f"Frühester Beginn ist der {_fmt(earliest)}.")
    if start > today + timedelta(days=MAX_ADVANCE_DAYS):
        raise QuoteError("Der Beginn liegt zu weit in der Zukunft.")
    if package is not None and package.duration_days:
        end = start + timedelta(days=package.duration_days - 1)
    else:
        if data.end_date is None:
            raise QuoteError("Bitte das Ende des Zeitraums wählen.")
        end = data.end_date
        if end < start:
            raise QuoteError("Das Ende liegt vor dem Beginn.")
    days = (end - start).days + 1
    if days > MAX_PERIOD_DAYS:
        raise QuoteError(f"Der Zeitraum darf höchstens {MAX_PERIOD_DAYS} Tage lang sein.")
    return start, end, days


def _coverage_names(db: Session, ids: list | None) -> str:
    """Sendegebiete als Text für Kalkulation und PDF, z. B. „UKW Wien · DAB+ National“."""
    if not ids:
        return ""
    found = {a.id: a for a in db.query(CoverageArea).filter(CoverageArea.id.in_(ids))}
    return " · ".join(found[i].name for i in ids if i in found)


def calculate_quote(db: Session, data: QuoteIn, today: date | None = None) -> QuoteOut:
    today = today or date.today()
    cfg = get_settings(db)

    prod = data.production
    country = db.query(Country).filter(Country.code == data.country, Country.active.is_(True)).first()
    if country is None:
        raise QuoteError(f"Rechnungsland nicht verfügbar: {data.country}")
    stations = _load_active(db, Station, {i.station_id for i in data.items}, "Sender")
    slots = _load_active(db, TimeSlot, {i.time_slot_id for i in data.items}, "Zeitschiene")
    length_ids = {i.spot_length_id for i in data.items} | ({prod.spot_length_id} if prod else set())
    lengths = _load_active(db, SpotLength, length_ids, "Spotlänge")
    addons = _load_active(db, AddOn, set(data.addon_ids), "Zusatzleistung")
    package = None
    if data.package_id is not None:
        package = _load_active(db, Package, {data.package_id}, "Komplettpaket")[data.package_id]
        if prod and package.max_seconds and lengths[prod.spot_length_id].seconds > package.max_seconds:
            raise QuoteError(f"„{package.name}“ gilt für Spots bis {package.max_seconds} Sek.")
    package_stations: list[Station] = []  # gewählter Sender bzw. alle enthaltenen Sender
    if package is not None and package.station_ids:
        if package.station_mode == "all":
            found = {s.id: s for s in db.query(Station).filter(Station.id.in_(package.station_ids),
                                                               Station.active.is_(True))}
            package_stations = [found[i] for i in package.station_ids if i in found]
        else:
            if data.package_station_id not in package.station_ids:
                raise QuoteError(f"Bitte für „{package.name}“ einen Sender wählen.")
            package_stations = [_load_active(db, Station, {data.package_station_id}, "Sender")[data.package_station_id]]

    period = booking_period(data, package, cfg["booking_lead_days"], today)

    studio_in_package = bool(package and package.includes_studio)
    if package and prod and prod.studio and not studio_in_package and not package.studio_bookable:
        raise QuoteError(f"Zu „{package.name}“ ist kein Studiospot buchbar.")
    studio = bool(prod and prod.studio) or studio_in_package
    blocked = [a.name for a in addons.values() if a.requires_studio and not studio]
    if blocked:
        raise QuoteError(f"Nur zusammen mit dem Studiospot buchbar: {', '.join(blocked)}")

    # --- Spotproduktion
    production_out: QuoteProduction | None = None
    if prod:
        voice = _load_active(db, Voice, {prod.voice_id}, "Stimme")[prod.voice_id]
        music = None
        if prod.music_style_id is not None:
            music = _load_active(db, MusicStyle, {prod.music_style_id}, "Musikrichtung")[prod.music_style_id]
        production_out = QuoteProduction(
            seconds=lengths[prod.spot_length_id].seconds, voice=voice.name,
            music=music.name if music else None, studio=studio, in_package=studio_in_package,
            total_cent=cfg["studio_price_cent"] if prod.studio and not studio_in_package else 0,
        )

    # --- Positionen
    lines: list[_Line] = []
    out_lines: list[QuoteLine] = []
    for item in data.items:
        st, ts, sl = stations[item.station_id], slots[item.time_slot_id], lengths[item.spot_length_id]
        unit = _round(Decimal(sl.seconds) * st.price_per_second_cent * ts.price_factor_bp / 10_000)
        total = unit * item.spots
        lines.append(_Line(station_id=st.id, total_cent=total, ad_tax_applies=st.ad_tax_applies))
        out_lines.append(
            QuoteLine(
                station=st.name, kind=st.kind, coverage=_coverage_names(db, st.coverage_ids),
                time_slot=ts.name, seconds=sl.seconds,
                spots=item.spots, unit_price_cent=unit, total_cent=total,
            )
        )

    airtime = sum(l.total_cent for l in lines)
    production_total = production_out.total_cent if production_out else 0
    addon_total = sum(a.price_cent for a in addons.values())
    package_total = package.price_cent if package else 0
    subtotal = airtime + production_total + addon_total + package_total
    total_spots = sum(i.spots for i in data.items) + (package.spots if package else 0)
    promo = data.promo_code.strip() if data.promo_code and data.promo_code.strip() else None

    # --- Rabatte
    stackable: list[tuple[Discount, int]] = []
    exclusive: list[tuple[Discount, int]] = []
    promo_matched = False
    candidates = list(db.query(Discount).filter(Discount.active.is_(True)).order_by(Discount.sort_order, Discount.id))
    wheel_discount = wheel.discount_from_token(db, data.wheel_token)
    if wheel_discount is not None:
        candidates.insert(0, wheel_discount)
    for d in candidates:
        base = _discount_base(d, lines, airtime, production_total, addon_total, package_total)
        if not _is_eligible(d, today=today, total_spots=total_spots, base=base, promo_code=promo):
            continue
        amount = _discount_amount(d, base)
        if amount <= 0:
            continue
        if d.promo_code:
            promo_matched = True
        (stackable if d.stackable else exclusive).append((d, amount))

    stack_sum = sum(a for _, a in stackable)
    best_exclusive = max(exclusive, key=lambda x: x[1], default=None)
    chosen = [best_exclusive] if best_exclusive and best_exclusive[1] > stack_sum else stackable

    # Werbeabgabepflichtige Sendezeit (Radio); Rabatte werden anteilig herausgerechnet
    taxable_lines = sum(l.total_cent for l in lines if l.ad_tax_applies)
    taxable = taxable_lines + (package.ad_tax_base_cent if package else 0)
    taxable_stations = {l.station_id for l in lines if l.ad_tax_applies}

    applied: list[AppliedDiscount] = []
    remaining = subtotal
    taxable_discount = Decimal(0)
    for d, amount in chosen:
        amount = min(amount, remaining)
        if amount <= 0:
            break
        remaining -= amount
        if d.station_id is not None:
            taxable_discount += amount if d.station_id in taxable_stations else 0
        elif d.applies_to == DiscountScope.airtime:
            taxable_discount += Decimal(amount) * taxable_lines / airtime
        elif d.applies_to == DiscountScope.total:
            taxable_discount += Decimal(amount) * taxable / subtotal
        applied.append(AppliedDiscount(name=d.name, description=d.description, amount_cent=amount))

    promo_applied = any(d.promo_code for d, _ in chosen)
    promo_status = None if promo is None else ("applied" if promo_applied else "invalid")
    if promo and promo_matched and not promo_applied:
        # Code ist gültig, aber ein besserer exklusiver/kombinierter Rabatt wurde gewählt.
        promo_status = "superseded"

    wheel_status = None
    if data.wheel_token:
        wheel_status = ("invalid" if wheel_discount is None
                        else "applied" if any(d is wheel_discount for d, _ in chosen) else "superseded")

    discount_total = subtotal - remaining
    net = remaining
    ad_tax_base = max(0, min(taxable - _round(taxable_discount), net))
    ad_tax = _bp(ad_tax_base, cfg["ad_tax_rate_bp"])
    vat_base = net + ad_tax if cfg["ad_tax_in_vat_base"] else net
    # Länder mit Reverse Charge + UID-Nummer → Nettorechnung (Steuerschuld beim Leistungsempfänger)
    reverse_charge = country.reverse_charge and bool(data.vat_id)
    vat_rate = 0 if reverse_charge else country.vat_rate_bp
    vat = _bp(vat_base, vat_rate)

    return QuoteOut(
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        period_days=period[2] if period else None,
        currency=cfg["currency"],
        country=data.country,
        country_name=country.name,
        vat_id=data.vat_id,
        reverse_charge=reverse_charge,
        production=production_out,
        package=QuotePackage(name=package.name, article_no=package.article_no or "",
                             description=package.description, spots=package.spots,
                             station=" + ".join(s.name for s in package_stations),
                             coverage=_coverage_names(db, package.coverage_ids or list(dict.fromkeys(
                                 i for s in package_stations for i in (s.coverage_ids or [])))),
                             includes_studio=package.includes_studio, price_cent=package.price_cent) if package else None,
        lines=out_lines,
        addons=[QuoteAddOn(name=a.name, price_cent=a.price_cent) for a in addons.values()],
        total_spots=total_spots,
        production_subtotal_cent=production_total,
        package_subtotal_cent=package_total,
        airtime_subtotal_cent=airtime,
        addons_subtotal_cent=addon_total,
        subtotal_cent=subtotal,
        discounts=applied,
        discount_total_cent=discount_total,
        net_cent=net,
        ad_tax_rate_bp=cfg["ad_tax_rate_bp"],
        ad_tax_base_cent=ad_tax_base,
        ad_tax_cent=ad_tax,
        vat_rate_bp=vat_rate,
        vat_base_cent=vat_base,
        vat_cent=vat,
        gross_cent=net + ad_tax + vat,
        promo_code_status=promo_status,
        wheel_status=wheel_status,
        meets_minimum_order=net >= cfg["min_order_cent"],
        min_order_cent=cfg["min_order_cent"],
    )
