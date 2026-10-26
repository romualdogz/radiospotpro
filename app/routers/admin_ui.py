"""Admin-Oberfläche (serverseitig gerendert, kein Build-Schritt nötig).

Die Formulare arbeiten mit Euro- und Prozentwerten; intern wird in Cent bzw.
Basispunkten gespeichert. Jede Produktart wird über eine Feldliste beschrieben,
die Templates sind generisch.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import re
from typing import Any, Callable
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from starlette.concurrency import run_in_threadpool

from .. import audio, branding, fonts, mailer, music_mix, theme, watermark, wheel
from ..config import BASE_DIR
from ..database import get_db
from ..models import (
    STATES, AddOn, AdminUser, Country, CoverageArea, Package, Discount, LegalText, DiscountKind, DiscountScope, LanguageStyle, MusicStyle, Occasion, QuoteRequest, SpotLength,
    Station, TimeSlot, Tonality, Voice,
)
from ..security import authenticate, check_csrf, csrf_token, current_admin_or_none, hash_password, verify_password
from ..settings_store import get_settings, save_settings

router = APIRouter(prefix="/admin", include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --------------------------------------------------------------------------- Formatierung

def fmt_eur(cent: int | None) -> str:
    if cent is None:
        return ""
    s = f"{cent / 100:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def fmt_bp(bp: int | None, suffix: str = " %") -> str:
    if bp is None:
        return ""
    return f"{bp / 100:g}".replace(".", ",") + suffix


templates.env.filters["eur"] = fmt_eur


def _static_version() -> str:
    """Kennung der aktuellen JS-/CSS-Dateien – hängt als ?v=… an, damit Browser nach Updates neu laden."""
    stamp = "".join(f"{f.name}{f.stat().st_mtime_ns}{f.stat().st_size}"
                    for f in sorted((BASE_DIR / "static").glob("*.[jc]s*")))
    return hashlib.sha1(stamp.encode()).hexdigest()[:10]


templates.env.globals["static_v"] = _static_version()
templates.env.filters["pct"] = fmt_bp
templates.env.filters["de_date"] = lambda v: date.fromisoformat(str(v)).strftime("%d.%m.%Y") if v else ""


def _parse_decimal(raw: str, label: str) -> Decimal:
    """Akzeptiert 1990 · 1990,00 · 1.990,00 · 1990.5 (mit Komma ist der Punkt ein Tausendertrennzeichen)."""
    raw = raw.strip().replace(" ", "").replace("€", "").replace("%", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as e:
        raise ValueError(f"{label}: ungültige Zahl") from e


# --------------------------------------------------------------------------- Feld-Definitionen

@dataclass
class F:
    name: str
    label: str
    type: str = "text"  # text, textarea, int, money, percent, factor, bool, time, date, select, multi, color, file
    required: bool = False
    help: str = ""
    options: Callable[[Session], list[tuple[str, str]]] | None = None
    in_list: bool = True

    def to_form(self, value: Any) -> str | list[str]:
        if self.type == "multi":
            return [str(v) for v in (value or [])]
        if value is None:
            return ""
        if self.type == "money":
            return f"{value / 100:.2f}".replace(".", ",")
        if self.type == "percent":
            return f"{value / 100:g}".replace(".", ",")
        if self.type == "factor":
            return f"{value / 10_000:g}".replace(".", ",")
        if self.type == "date":
            return value.isoformat()
        if hasattr(value, "value"):  # Enum
            return value.value
        return str(value)

    def display(self, value: Any) -> str:
        if self.type == "money":
            return fmt_eur(value)
        if self.type == "percent":
            return fmt_bp(value)
        if self.type == "factor":
            return "×" + self.to_form(value)
        if self.type == "bool":
            return "✔" if value else "–"
        if self.type == "date":
            return value.strftime("%d.%m.%Y") if value else ""
        if self.type == "file":
            return "✔ vorhanden" if value else "–"
        if self.type == "color":
            return value or "Standard"
        return self.to_form(value)

    def parse(self, raw: str | list | None) -> Any:
        if self.type == "multi":  # Liste aus Checkboxen
            values = [int(v) if str(v).isdigit() else str(v) for v in (raw or []) if str(v).strip()]
            if self.required and not values:
                raise ValueError(f"{self.label}: bitte mindestens einen Eintrag wählen")
            return values
        raw = (raw or "").strip()
        if self.type == "bool":
            return raw == "on"
        if not raw:
            if self.required:
                raise ValueError(f"{self.label} ist ein Pflichtfeld")
            return {"int": 0, "money": 0, "percent": 0, "text": "", "textarea": "", "time": "", "color": ""}.get(self.type)
        if self.type == "int":
            try:
                return int(raw)
            except ValueError as e:
                raise ValueError(f"{self.label}: ganze Zahl erwartet") from e
        if self.type == "money":
            return int((_parse_decimal(raw, self.label) * 100).to_integral_value())
        if self.type == "percent":
            return int((_parse_decimal(raw, self.label) * 100).to_integral_value())
        if self.type == "factor":
            return int((_parse_decimal(raw, self.label) * 10_000).to_integral_value())
        if self.type == "date":
            try:
                return date.fromisoformat(raw)
            except ValueError as e:
                raise ValueError(f"{self.label}: ungültiges Datum") from e
        if self.type == "select" and raw.isdigit():
            return int(raw)
        if self.type == "color":
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
                raise ValueError(f"{self.label}: bitte eine Farbe im Format #RRGGBB wählen oder leer lassen")
            return raw.lower()
        return raw


@dataclass
class Entity:
    slug: str
    model: type
    title: str
    singular: str
    fields: list[F]
    group: str = "Produktion"
    # Zusätzliche Validierung/Umwandlung nach dem Parsen
    finalize: Callable[[dict], dict] = field(default=lambda d: d)


_VOICE_DEFAULTS = {"stability_bp": 5000, "similarity_bp": 7500, "style_bp": 0, "speed_bp": 10000}
_VOICE_FORM_DEFAULTS = {"stability_bp": "0,5", "similarity_bp": "0,75", "style_bp": "0", "speed_bp": "1"}


def _finalize_voice(d: dict) -> dict:
    """Leere KI-Regler auf Standardwerte setzen und auf erlaubte Bereiche begrenzen."""
    for key, default in _VOICE_DEFAULTS.items():
        d[key] = default if d.get(key) is None else d[key]
    for key in ("stability_bp", "similarity_bp", "style_bp"):
        d[key] = min(max(d[key], 0), 10_000)
    d["speed_bp"] = min(max(d["speed_bp"], 7_000), 12_000)
    return d


def _finalize_music(d: dict) -> dict:
    """Leere Korrektur = unverändert; sinnvoller Bereich 0,2–3."""
    d["gain_bp"] = 10_000 if not d.get("gain_bp") else d["gain_bp"]
    if not 2_000 <= d["gain_bp"] <= 30_000:
        raise ValueError("Lautstärke-Korrektur: bitte einen Wert zwischen 0,2 und 3 angeben (1 = unverändert)")
    return d


def _finalize_country(d: dict) -> dict:
    d["code"] = d["code"].strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", d["code"]):
        raise ValueError("Ländercode: bitte 2 Buchstaben, z. B. AT")
    if d["vat_rate_bp"] > 10_000:
        raise ValueError("MwSt.-Satz: höchstens 100 %")
    return d


def _coverage_options(db: Session) -> list[tuple[str, str]]:
    tech = {"dab": "DAB+", "ukw": "UKW"}
    return [(str(a.id), f"{a.name} ({tech.get(a.technology, a.technology)})")
            for a in db.query(CoverageArea).order_by(CoverageArea.sort_order, CoverageArea.id)]


def _finalize_coverage(d: dict) -> dict:
    valid = {k for k, _ in STATES}
    d["states"] = [s for s in d["states"] if s in valid]
    for key, label, lo, hi in (("center_lat", "Breitengrad", 45.5, 49.5), ("center_lon", "Längengrad", 9.0, 17.5)):
        raw = (d.get(key) or "").strip().replace(",", ".")
        if not raw:
            d[key] = None
            continue
        try:
            value = float(raw)
        except ValueError as e:
            raise ValueError(f"Sender-Standort ({label}): bitte eine Zahl angeben – am einfachsten auf die Karte klicken") from e
        if not lo <= value <= hi:
            raise ValueError("Sender-Standort liegt nicht in Österreich – bitte auf die Karte klicken")
        d[key] = value
    has_circle = d["center_lat"] is not None and d["center_lon"] is not None and d["radius_km"] > 0
    if (d["center_lat"] is None) != (d["center_lon"] is None):
        raise ValueError("Sender-Standort: bitte auf die Karte klicken (Breiten- und Längengrad nötig)")
    if d["radius_km"] > 300:
        raise ValueError("Radius: höchstens 300 km")
    if d["technology"] == "dab" and not d["states"]:
        raise ValueError("DAB+: bitte die Bundesländer wählen, in denen der Multiplex sendet (national = alle)")
    if d["technology"] == "ukw" and not d["states"] and not has_circle:
        raise ValueError("UKW: bitte Bundesländer wählen oder den Sender-Standort mit Radius angeben")
    return d


def _finalize_package(d: dict) -> dict:
    d["article_no"] = d.get("article_no", "").strip()[:40]
    if not 0 <= d.get("duration_days", 0) <= 366:
        raise ValueError("Laufzeit: 0 bis 366 Tage")
    if not 0 <= d.get("recommended_days", 0) <= 366:
        raise ValueError("Empfohlene Laufzeit: 0 bis 366 Tage")
    if d["airtime_cent"] > d["price_cent"]:
        raise ValueError("Der Sendezeit-Anteil kann nicht höher als der Paketpreis sein")
    if not 0 <= d["max_seconds"] <= 300:
        raise ValueError("Spotlänge: 0 bis 300 Sekunden")
    return d


def _station_options(db: Session) -> list[tuple[str, str]]:
    return [("", "— alle Sender —")] + [
        (str(s.id), s.name) for s in db.query(Station).order_by(Station.sort_order, Station.id)
    ]


def _finalize_discount(d: dict) -> dict:
    d["kind"] = DiscountKind(d["kind"])
    d["applies_to"] = DiscountScope(d["applies_to"])
    d["promo_code"] = d["promo_code"] or None
    d["station_id"] = d["station_id"] or None
    # Prozent-Rabatte werden als Basispunkte gespeichert, Fixbeträge als Cent:
    raw = d.pop("value_raw")
    dec = _parse_decimal(raw, "Wert")
    d["value"] = int((dec * 100).to_integral_value())
    if d["kind"] == DiscountKind.percent and d["value"] > 10_000:
        raise ValueError("Ein Prozentrabatt darf höchstens 100 % betragen")
    if d["valid_from"] and d["valid_until"] and d["valid_from"] > d["valid_until"]:
        raise ValueError("„Gültig ab“ liegt nach „Gültig bis“")
    return d


_NAME_FIELDS = [
    F("name", "Name", required=True),
    F("sort_order", "Sortierung", "int"),
    F("active", "Aktiv / auswählbar", "bool"),
]

ENTITIES: dict[str, Entity] = {
    e.slug: e for e in [
        Entity("spot-lengths", SpotLength, "Spotlängen", "Spotlänge", [
            F("seconds", "Sekunden", "int", required=True),
            F("label", "Bezeichnung"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / buchbar", "bool"),
        ]),
        Entity("voices", Voice, "Stimmen", "Stimme", [
            F("name", "Name", required=True),
            F("tag", "Beschreibung", help="z. B. „warm, vertrauensbildend · weiblich“"),
            F("tier", "Badge", help="z. B. Demo"),
            F("elevenlabs_voice_id", "ElevenLabs Voice-ID",
              help="Aus der ElevenLabs Voice Library („Copy voice ID“). Leer = Browser-Stimme als Ersatz"),
            F("sample_url", "Eigene Hörprobe (URL zu MP3, optional)", in_list=False,
              help="Ersetzt die automatische Stimmprobe"),
            F("stability_bp", "KI-Stimme: Stabilität (0–1)", "factor", in_list=False,
              help="Niedrig = mehr Emotion und Dynamik, hoch = ruhig und gleichmäßig. Standard 0,5"),
            F("similarity_bp", "KI-Stimme: Ähnlichkeit (0–1)", "factor", in_list=False,
              help="Wie nah an der Originalstimme. Standard 0,75"),
            F("style_bp", "KI-Stimme: Style (0–1)", "factor", in_list=False,
              help="Verstärkt den Sprechstil – nur Multilingual v2 / Flash (nicht Eleven v4). Standard 0"),
            F("speed_bp", "KI-Stimme: Tempo (0,7–1,2)", "factor", in_list=False,
              help="1 = normal – nur Multilingual v2 / Flash (bei Eleven v4 über Text/Regieanweisungen)"),
            F("pitch_bp", "Browser-Vorschau: Tonhöhe", "factor", in_list=False, help="1 = normal"),
            F("rate_bp", "Browser-Vorschau: Tempo", "factor", in_list=False, help="1 = normal"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / auswählbar", "bool"),
        ], finalize=_finalize_voice),
        Entity("music-styles", MusicStyle, "Musik", "Musikrichtung", [
            F("name", "Name", required=True),
            F("audio_file", "Musikdatei (MP3, WAV, OGG, FLAC – max. 20 MB)", "file",
              help="Lizenzfreie Musik verwenden. Leer lassen = „keine Musik“. Neue Datei ersetzt die alte."),
            F("gain_bp", "Lautstärke-Korrektur (Faktor)", "factor",
              help="1 = unverändert, z. B. 0,7 = leiser, 1,3 = lauter. Gleicht Stücke aus, die von Haus aus lauter "
                   "oder leiser klingen. Die Grundlautstärke stellst du unter Einstellungen → Hintergrundmusik ein."),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / auswählbar", "bool"),
        ], finalize=_finalize_music),
        Entity("occasions", Occasion, "Anlässe", "Anlass", _NAME_FIELDS),
        Entity("tonalities", Tonality, "Tonalitäten", "Tonalität", [
            F("name", "Name", required=True),
            F("delivery_hint", "Sprech-Dynamik für die KI", in_list=False,
              help="Beschreibung + passende Regieanweisungen, z. B. „energiegeladen – [excited], [urgently]“ (Eleven v4)"),
            F("stability_bp", "Stabilität (leer = Wert der Stimme)", "factor", in_list=False,
              help="Niedriger = mehr Emotion"),
            F("style_bp", "Style (leer = Wert der Stimme)", "factor", in_list=False, help="nur Multilingual v2 / Flash"),
            F("speed_bp", "Tempo-Faktor (leer = 1)", "factor", in_list=False,
              help="z. B. 1,1 = 10 % schneller – nur Multilingual v2 / Flash"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / auswählbar", "bool"),
        ]),
        Entity("language-styles", LanguageStyle, "Sprachstile", "Sprachstil", [
            F("name", "Name", required=True),
            F("instruction", "Anweisung an die KI", "textarea", in_list=False,
              help="Wird bei „Text mit KI generieren“ mitgeschickt"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / auswählbar", "bool"),
        ]),
        Entity("stations", Station, "Sender & Streams", "Sender / Stream", [
            F("name", "Name", required=True),
            F("kind", "Typ", "select", required=True,
              options=lambda _db: [("radio", "Radio"), ("stream", "Stream (Energy-Gruppe)")]),
            F("region", "Region"),
            F("price_per_second_cent", "Sekundenpreis (€)", "money", required=True,
              help="Netto-Preis pro Sekunde Sendezeit"),
            F("ad_tax_applies", "Werbeabgabe fällt an", "bool",
              help="Radio: ja. Online-Streams sind in der Regel von der Werbeabgabe ausgenommen."),
            F("coverage_ids", "Sendegebiete", "multi", options=_coverage_options,
              help="Werden im Konfigurator auf der Österreich-Karte angezeigt. Sendegebiete pflegst du unter "
                   "Schaltung → Sendegebiete."),
            F("map_color", "Farbe auf der Karte", "color",
              help="Die Sendegebiete dieses Senders leuchten in dieser Farbe, z. B. Blau für Radio Nostalgie. "
                   "Leer = Farbe des Sendegebiets bzw. Akzentfarbe."),
            F("description", "Beschreibung", "textarea", in_list=False),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / buchbar", "bool"),
        ], group="Schaltung"),
        Entity("coverage", CoverageArea, "Sendegebiete", "Sendegebiet", [
            F("name", "Name", required=True, help="Wird Kunden angezeigt, z. B. „UKW Wien“ oder „DAB+ National“"),
            F("technology", "Technik", "select", required=True,
              options=lambda _db: [("dab", "DAB+ (digital, landesweit über Multiplex)"), ("ukw", "UKW (analog, regional)")]),
            F("states", "Bundesländer, die aufleuchten", "multi", options=lambda _db: STATES,
              help="DAB+ National = alle Bundesländer. Bei UKW mit Sender-Standort zeigt die Karte nur den Kreis – "
                   "die Bundesländer leuchten bei UKW nur, wenn kein Standort eingetragen ist."),
            F("center_lat", "Sender-Standort: Breitengrad", in_list=False,
              help="Am einfachsten unten auf die Karte klicken – die Werte werden dann automatisch eingetragen"),
            F("center_lon", "Sender-Standort: Längengrad", in_list=False),
            F("radius_km", "Radius um den Sender (km)", "int", help="0 = kein Kreis. UKW-Sender reichen meist 25–60 km"),
            F("reach_text", "Reichweite / Hinweis für Kunden",
              help="z. B. „Wien und Umgebung“ oder „ganz Österreich – Empfang mit DAB+-Radio“"),
            F("color", "Farbe auf der Karte", "color",
              help="Leer = Akzentfarbe aus dem Design. Hat der Sender eine eigene Kartenfarbe, gilt diese."),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv", "bool"),
        ], group="Schaltung", finalize=_finalize_coverage),
        Entity("time-slots", TimeSlot, "Zeitschienen", "Zeitschiene", [
            F("name", "Name", required=True),
            F("start_time", "Von", "time"),
            F("end_time", "Bis", "time"),
            F("price_factor_bp", "Preisfaktor", "factor", required=True,
              help="Multiplikator auf den Sekundenpreis, z. B. 1,5 für Prime Time"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / buchbar", "bool"),
        ], group="Schaltung"),
        Entity("packages", Package, "Komplettpakete", "Komplettpaket", [
            F("name", "Name", required=True),
            F("article_no", "Artikelnummer", help="Erscheint in Anfrage, PDF und E-Mail-Kalkulation, z. B. „PKT-1001“"),
            F("badge", "Badge", help="Kurzer Hinweis auf der Paketkarte, z. B. „Beliebt“ – optional"),
            F("price_cent", "Pauschalpreis (€, netto)", "money", required=True),
            F("description", "Leistungen (eine pro Zeile)", "textarea", in_list=False,
              help="z. B. „40 Ausstrahlungen auf Radio Energy Österreich“, „Laufzeit 2 Wochen“"),
            F("spots", "Schaltungen (Ausstrahlungen gesamt)", "int",
              help="Anzahl der Ausstrahlungen im Paket – wird angezeigt und zählt für Mengenrabatte"),
            F("duration_days", "Laufzeit (Tage)", "int",
              help="Der Kunde wählt nur den Beginn, das Ende ergibt sich aus der Laufzeit (z. B. 14 = zwei Wochen). "
                   "0 = Kunde wählt Beginn und Ende selbst."),
            F("recommended_days", "Empfohlene Laufzeit (Tage)", "int",
              help="Empfehlung für den Verkauf, z. B. 28 = vier Wochen. Wird gespeichert, im Konfigurator aber "
                   "noch nicht angezeigt (für eine spätere Funktion). 0 = keine Empfehlung."),
            F("max_seconds", "Für Spots bis … Sek.", "int", in_list=False,
              help="0 = jede Spotlänge. Längere Spots können das Paket nicht wählen"),
            F("includes_studio", "Studiospot inklusive", "bool",
              help="Der Studiospot mit echtem Sprecher ist im Pauschalpreis enthalten"),
            F("studio_bookable", "Studiospot zubuchbar", "bool", in_list=False,
              help="Ausschalten bei Paketen ohne Werbespot (z. B. Gewinnspiel, Sponsoring, Moderation) – "
                   "der Kunde kann dann keinen Studiospot wählen. Gilt nicht, wenn „Studiospot inklusive“ an ist."),
            F("ad_tax_applies", "Werbeabgabe fällt an", "bool", in_list=False,
              help="Bei reinen Stream-Paketen ausschalten"),
            F("station_ids", "Wählbare Sender", "multi", options=lambda db: [
                (str(s.id), s.name) for s in db.query(Station).order_by(Station.sort_order, Station.id)],
              help="Sender dieses Pakets. Nichts angehakt = fester Sendeumfang nur über die Sendegebiete unten."),
            F("station_mode", "Senderwahl", "select", in_list=False,
              options=lambda _db: [("choose", "Kunde wählt einen der angehakten Sender"),
                                   ("all", "Alle angehakten Sender sind im Paket enthalten")],
              help="„Alle enthalten“: keine Auswahl – die Karte zeigt jeden Sender in seiner Farbe, "
                   "z. B. Energy rot und Nostalgie blau."),
            F("coverage_ids", "Sendegebiete", "multi", options=_coverage_options, in_list=False,
              help="Werden im Konfigurator auf der Österreich-Karte angezeigt (in der Farbe des gewählten Senders). "
                   "Leer lassen = Sendegebiete des gewählten Senders."),
            F("airtime_cent", "Davon Radio-Sendezeit (€) – Basis der Werbeabgabe", "money", in_list=False,
              help="0 = Werbeabgabe auf den gesamten Paketpreis. Bei Paketen mit Studiospot hier nur den Sendezeit-Anteil eintragen"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / buchbar", "bool"),
        ], group="Preise", finalize=_finalize_package),
        Entity("addons", AddOn, "Zusatzleistungen", "Zusatzleistung", [
            F("name", "Name", required=True),
            F("price_cent", "Preis (€, netto)", "money", required=True),
            F("description", "Beschreibung", "textarea", in_list=False),
            F("requires_studio", "Nur mit Studiospot", "bool",
              help="Wird im Konfigurator nur angezeigt, wenn der Studiospot gewählt ist"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / buchbar", "bool"),
        ], group="Preise"),
        Entity("countries", Country, "Länder", "Land", [
            F("name", "Name", required=True),
            F("code", "Ländercode (ISO, 2 Buchstaben)", required=True, help="z. B. AT, DE, CH"),
            F("vat_rate_bp", "MwSt.-Satz (%)", "percent", required=True, help="Erscheint auf Kostenaufstellung und Rechnung"),
            F("reverse_charge", "Mit UID-Nummer: Nettorechnung (Reverse Charge)", "bool",
              help="Bei Firmenkunden mit gültiger UID wird 0 % MwSt. berechnet"),
            F("sort_order", "Sortierung", "int"),
            F("active", "Aktiv / auswählbar", "bool"),
        ], group="Preise", finalize=_finalize_country),
        Entity("discounts", Discount, "Rabatte", "Rabatt", [
            F("name", "Name", required=True),
            F("description", "Beschreibung (für Kunden sichtbar)", "textarea", in_list=False),
            F("kind", "Art", "select", required=True,
              options=lambda _db: [("percent", "Prozent"), ("fixed", "Fixbetrag (€)")]),
            F("value_raw", "Wert", required=True, help="Prozent (z. B. 10) bzw. Euro (z. B. 100,00)"),
            F("applies_to", "Gilt für", "select",
              options=lambda _db: [("total", "Gesamtbetrag"), ("production", "Nur Studiospot"),
                                 ("airtime", "Nur Sendezeit (Schaltung)")]),
            F("min_spots", "Mindestanzahl Spots", "int", help="0 = keine Bedingung"),
            F("min_amount_cent", "Mindestbetrag (€)", "money", help="Bezogen auf die rabattfähige Basis"),
            F("promo_code", "Gutscheincode", help="Leer = automatisch; sonst nur mit Code"),
            F("station_id", "Nur für Sender", "select", options=_station_options, in_list=False,
              help="Rabatt bezieht sich dann nur auf die Sendezeit dieses Senders"),
            F("valid_from", "Gültig ab", "date", in_list=False),
            F("valid_until", "Gültig bis", "date", in_list=False),
            F("stackable", "Mit anderen kombinierbar", "bool",
              help="Nicht kombinierbare Rabatte greifen nur, wenn sie allein günstiger sind"),
            F("sort_order", "Sortierung", "int", in_list=False),
            F("active", "Aktiv", "bool"),
        ], group="Preise", finalize=_finalize_discount),
    ]
}


def _form_value(entity: Entity, f: F, obj: Any) -> str:
    if obj is None:
        if f.type == "multi":
            return []
        return {"active": "on", "technology": "ukw", "stackable": "on", "price_factor_bp": "1", "pitch_bp": "1", "rate_bp": "1",
                "kind": "percent", "tier": "Demo", "ad_tax_applies": "on", "studio_bookable": "on", "max_seconds": "0", "gain_bp": "1", "station_mode": "choose", "duration_days": "0", "recommended_days": "0", "reverse_charge": "on",
                **({"vat_rate_bp": "20"} if entity.slug == "countries" else {}),
                **(_VOICE_FORM_DEFAULTS if entity.slug == "voices" else {})}.get(f.name, "")
    if f.name == "value_raw":  # Rabattwert je nach Art
        if obj.kind == DiscountKind.percent:
            return f"{obj.value / 100:g}".replace(".", ",")
        return f"{obj.value / 100:.2f}".replace(".", ",")
    value = getattr(obj, f.name)
    if f.type == "bool":
        return "on" if value else ""
    return f.to_form(value)


def _list_value(entity: Entity, f: F, obj: Any, options: dict | None = None) -> str:
    if f.name == "value_raw":
        return fmt_bp(obj.value) if obj.kind == DiscountKind.percent else fmt_eur(obj.value)
    if f.type == "multi":
        labels = dict((options or {}).get(f.name, []))
        return ", ".join(labels.get(v, v) for v in f.to_form(getattr(obj, f.name))) or "–"
    if f.type == "select" and f.options:
        raw = f.to_form(getattr(obj, f.name))
        return dict((options or {}).get(f.name) or f.options(None)).get(raw, raw)
    return f.display(getattr(obj, f.name))


# --------------------------------------------------------------------------- Helpers

class _LoginRequired(Exception):
    pass


class _Forbidden(Exception):
    def __init__(self, user):
        self.user = user


ROLES = {"admin": "Administrator", "sales": "Verkaufsleitung"}
# Bereiche, die die Verkaufsleitung sehen und bearbeiten darf – alles andere nur Admins
SALES_SECTIONS = {"stations", "coverage", "time-slots", "packages", "addons", "discounts", "countries", "prices",
                  "wheel", "account"}


def can(user, section: str) -> bool:
    return user is not None and (user.role == "admin" or section in SALES_SECTIONS)


def admin_page(request: Request, db: Session = Depends(get_db)):
    """Jeder angemeldete Benutzer (Admin oder Verkaufsleitung)."""
    user = current_admin_or_none(request, db)
    if user is None:
        raise _LoginRequired()
    return user


def admin_only(user=Depends(admin_page)):
    if user.role != "admin":
        raise _Forbidden(user)
    return user


def section_page(section: str):
    def dependency(user=Depends(admin_page)):
        if not can(user, section):
            raise _Forbidden(user)
        return user
    return dependency


NAV_GROUPS: dict[str, list[Entity]] = {}
for _e in ENTITIES.values():
    NAV_GROUPS.setdefault(_e.group, []).append(_e)


def _nav_for(user) -> dict[str, list[Entity]]:
    groups = {g: [e for e in items if can(user, e.slug)] for g, items in NAV_GROUPS.items()}
    return {g: items for g, items in groups.items() if items}


def render(request: Request, template: str, **ctx):
    ctx.setdefault("entities", ENTITIES)
    ctx.setdefault("nav_groups", _nav_for(ctx.get("user")))
    ctx.setdefault("can", lambda section: can(ctx.get("user"), section))
    ctx.setdefault("roles", ROLES)
    return templates.TemplateResponse(request, template, {"csrf": csrf_token(request), **ctx})


def forbidden_page(request: Request, user):
    response = render(request, "admin/forbidden.html", user=user)
    response.status_code = 403
    return response


def redirect(url: str, flash: str | None = None, request: Request | None = None):
    if flash and request is not None:
        request.session["flash"] = flash
    return RedirectResponse(url, status_code=303)


def pop_flash(request: Request) -> str | None:
    return request.session.pop("flash", None)


# --------------------------------------------------------------------------- Login

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "admin/login.html", error=None)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = authenticate(db, username, password)
    if user is None:
        return render(request, "admin/login.html", error="Benutzername oder Passwort falsch.")
    request.session.clear()
    request.session["admin_id"] = user.id
    return redirect("/admin")


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return redirect("/admin/login")


# --------------------------------------------------------------------------- Dashboard & Einstellungen

def _without_coverage(db: Session) -> list[tuple[str, str]]:
    """Aktive Radiosender und Pakete, für die die Reichweiten-Karte nichts anzeigen kann."""
    if not db.query(CoverageArea).count():
        return []
    stations = db.query(Station).filter(Station.active.is_(True)).order_by(Station.sort_order, Station.id).all()
    with_cov = {s.id for s in stations if s.coverage_ids}
    out = [(f"Sender „{s.name}“", f"/admin/stations/{s.id}") for s in stations
           if s.kind == "radio" and not s.coverage_ids]
    for p in db.query(Package).filter(Package.active.is_(True)).order_by(Package.sort_order, Package.id):
        if p.coverage_ids:
            continue
        if not p.station_ids or not any(i in with_cov for i in p.station_ids):
            out.append((f"Paket „{p.name}“", f"/admin/packages/{p.id}"))
    return out


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(admin_page), db: Session = Depends(get_db)):
    if user.role != "admin":
        return _sales_home(request, user, db)
    counts = {slug: db.query(e.model).count() for slug, e in ENTITIES.items()}
    open_requests = db.query(QuoteRequest).filter(QuoteRequest.status == "neu").count()
    from .. import ai
    return render(request, "admin/dashboard.html", user=user, counts=counts,
                  open_requests=open_requests, ai_enabled=ai.is_enabled(), ai_model=ai.MODEL,
                  legal_placeholders=[t.title for t in db.query(LegalText) if t.is_placeholder or not t.body.strip()],
                  tts_enabled=audio.tts_enabled(), tts_model=audio.MODEL, tts_tags=audio.supports_audio_tags(),
                  mail_enabled=mailer.is_configured(), mail_from=mailer.config().sender,
                  voices_without_id=[v for v in db.query(Voice).filter(Voice.active.is_(True))
                                     .order_by(Voice.sort_order, Voice.id) if not v.has_tts],
                  without_coverage=_without_coverage(db),
                  flash=pop_flash(request))


SALES_TILES = {  # Startseite der Verkaufsleitung: Bereich → kurze Erklärung
    "packages": "Pauschalpakete mit Preis, Laufzeit und Sendern",
    "stations": "Radiosender und Streams mit Sekundenpreisen",
    "time-slots": "Zeitschienen und Aufschläge",
    "coverage": "Sendegebiete für die Reichweiten-Karte",
    "addons": "Zusatzleistungen wie Express-Produktion",
    "discounts": "Mengen-, Aktions- und Gutscheinrabatte",
    "countries": "Länder und Mehrwertsteuersätze",
}


def _sales_home(request: Request, user, db: Session):
    tiles = []
    for slug, info in SALES_TILES.items():
        e = ENTITIES[slug]
        total = db.query(e.model).count()
        active = (db.query(e.model).filter(e.model.active.is_(True)).count()
                  if hasattr(e.model, "active") else total)
        tiles.append({"slug": slug, "title": e.title, "info": info, "total": total, "active": active})
    packages = db.query(Package).order_by(Package.sort_order, Package.id).all()
    today = date.today()
    discounts = [d for d in db.query(Discount).filter(Discount.active.is_(True)).order_by(Discount.sort_order, Discount.id)
                 if (d.valid_until is None or d.valid_until >= today)]
    return render(request, "admin/sales_home.html", user=user, tiles=tiles, cfg=get_settings(db),
                  packages=[p for p in packages if p.active], inactive_packages=[p for p in packages if not p.active],
                  discounts=discounts, without_coverage=_without_coverage(db), today=today,
                  flash=pop_flash(request))


@router.get("/legal", response_class=HTMLResponse)
def legal_form(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    texts = db.query(LegalText).order_by(LegalText.id).all()
    return render(request, "admin/legal.html", user=user, texts=texts, flash=pop_flash(request), error=None)


@router.post("/legal/{key}")
def legal_save(key: str, request: Request, user=Depends(admin_only), db: Session = Depends(get_db),
               csrf: str = Form(""), title: str = Form(...), body: str = Form("")):
    check_csrf(request, csrf)
    text = db.query(LegalText).filter_by(key=key).first()
    if text is None:
        raise HTTPException(404)
    title, body = title.strip(), body.strip().replace("\r\n", "\n")
    if not title:
        return redirect("/admin/legal", "Bitte einen Titel angeben.", request)
    if (title, body) != (text.title, text.body):
        text.title, text.body = title, body
        text.updated_at = datetime.now(timezone.utc)
        db.commit()
    return redirect("/admin/legal", f"„{title}“ gespeichert.", request)


@router.get("/design", response_class=HTMLResponse)
def design_form(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    return render(request, "admin/design.html", user=user, design=theme.get_theme(db), error=None,
                  flash=pop_flash(request), **_design_context(db))


@router.post("/design/logo")
async def design_logo(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    action = form.get("action", "upload")
    if action == "remove":
        branding.remove_logo(db)
        return redirect("/admin/design", "Logo entfernt – im Konfigurator steht wieder der Schriftzug.", request)
    try:
        height = int(str(form.get("height") or branding.HEIGHT_DEFAULT))
    except ValueError:
        height = branding.HEIGHT_DEFAULT
    upload = form.get("logo")
    try:
        if getattr(upload, "filename", ""):
            branding.save_logo(db, upload.filename, await upload.read(MAX_LOGO_READ))
        elif action == "upload" and branding.get_logo(db) is None:
            raise ValueError("Bitte eine Bilddatei auswählen.")
    except ValueError as e:
        return render(request, "admin/design.html", user=user, design=theme.get_theme(db), error=str(e),
                      flash=None, **_design_context(db))
    branding.set_options(db, height, form.get("in_pdf") == "on")
    return redirect("/admin/design", "Logo gespeichert – Konfigurator neu laden, um es zu sehen.", request)


MAX_LOGO_READ = branding.MAX_BYTES + 1  # eine Byte mehr lesen, um zu große Dateien zu erkennen


def _design_context(db: Session) -> dict:
    groups: dict[str, list] = {}
    for key, (label, default, group) in theme.COLORS.items():
        groups.setdefault(group, []).append((key, label, default))
    layouts = {n: theme.variant_layout(n) for n in theme.VARIANTS}
    saved = theme.get_theme(db)
    return {"color_groups": groups, "fonts": theme.FONTS, "system_font": theme.SYSTEM_FONT,
            "presets": theme.PRESETS, "logo": branding.get_logo(db), "texts": theme.TEXTS,
            "layout_options": theme.LAYOUT, "variants": theme.VARIANTS,
            "variant_layouts": layouts, "current_variant": next(
                (n for n, lay in layouts.items() if all(saved[k] == v for k, v in lay.items())), None),
            "hero_size_limits": (theme.HERO_SIZE_MIN, theme.HERO_SIZE_DEFAULT, theme.HERO_SIZE_MAX),
            "logo_limits": (branding.HEIGHT_MIN, branding.HEIGHT_DEFAULT, branding.HEIGHT_MAX)}


@router.post("/design")
async def design_save(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    action = form.get("action", "save")
    if action == "reset":
        theme.reset_theme(db)
        return redirect("/admin/design", "Design auf die Vorlage zurückgesetzt.", request)
    if action.startswith("preset:"):
        preset = theme.PRESETS.get(action[7:])
        if preset is None:
            raise HTTPException(400, "Unbekannte Vorlage")
        current = theme.get_theme(db)
        theme.save_theme(db, {**current, **preset})
        return redirect("/admin/design", f"Farbvorlage „{action[7:]}“ übernommen.", request)
    if action.startswith("variant:"):
        variant = theme.VARIANTS.get(action[8:])
        if variant is None:
            raise HTTPException(400, "Unbekannte Variante")
        current = theme.get_theme(db)
        colors = theme.PRESETS[variant["colors"]] if variant["colors"] and form.get("with_colors") == "on" else {}
        theme.save_theme(db, {**current, **colors, **theme.variant_layout(action[8:])})
        extra = " mit passenden Farben" if colors else ""
        return redirect("/admin/design", f"Variante „{action[8:]}“{extra} übernommen.", request)
    if action == "layout":
        current = theme.get_theme(db)
        theme.save_theme(db, {**current, **{k: str(form.get(k, "")) for k in theme.LAYOUT_DEFAULTS}})
        return redirect("/admin/design", "Layout gespeichert – Konfigurator neu laden, um es zu sehen.", request)
    values = {**{k: v for k, v in theme.get_theme(db).items() if k in theme.LAYOUT_DEFAULTS},
              **{k: str(form.get(k, "")) for k in [*theme.COLORS, *theme.FONT_DEFAULTS, *theme.TEXTS, "hero_size"]}}
    for key in theme.FONT_DEFAULTS:  # eigene Google-Font statt Auswahl
        custom = str(form.get(f"{key}_custom", "")).strip()
        if values[key] == "custom":
            values[key] = custom
    try:
        clean = theme.validate(values)
        for family in theme.families(clean):  # eigene Google-Font einmalig auf den Server laden
            fonts.ensure_local(family)
        theme.save_theme(db, clean)
    except ValueError as e:
        return render(request, "admin/design.html", user=user, design={**theme.get_theme(db), **values},
                      error=str(e), flash=None, **_design_context(db))
    return redirect("/admin/design", "Design gespeichert – Konfigurator neu laden, um es zu sehen.", request)


def _render_settings(request: Request, user, db: Session, error=None, mail_default_to=None):
    return render(request, "admin/settings.html", user=user, cfg=get_settings(db), error=error,
                  flash=None if error else pop_flash(request),
                  mail_default_to=mailer.default_recipient(db) if mail_default_to is None else mail_default_to,
                  wm=watermark.get_config(db), mix=music_mix.get_levels(db), mix_limits=music_mix.LEVELS,
                  wm_limits=(watermark.VOLUME_MIN, watermark.VOLUME_MAX, watermark.MAX_SECONDS))


@router.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    return _render_settings(request, user, db)


@router.post("/settings")
async def settings_save(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf"))

    def field(name: str, default: str = "") -> str:
        return str(form.get(name) or default)

    mail_default_to = field("mail_default_to")
    current_wm = watermark.get_config(db)
    try:
        values = {
            "company_info": field("company_info").strip()[:255],
            "watermark_text": field("watermark_text").strip()[:120] or "Hörprobe von onaircraft",
            "watermark_interval_s": min(60, max(3, int(_parse_decimal(field("watermark_interval", "7"), "Wasserzeichen-Abstand")))),
            "master_lufs": min(-5.0, max(-30.0, float(_parse_decimal(field("master_lufs", "-8"), "Ziel-Lautheit")))),
            "master_ceiling_dbtp": min(0.0, max(-6.0, float(_parse_decimal(field("master_ceiling", "-1"), "True Peak")))),
        }
        try:
            wm_volume = int(field("watermark_volume", str(current_wm["volume"])))
        except ValueError:
            wm_volume = current_wm["volume"]
        mailer.save_default_recipient(db, mail_default_to)
        upload = form.get("watermark_upload")
        wm_mode = field("watermark_mode", current_wm["mode"])
        if form.get("watermark_remove") == "on":
            watermark.remove_file(db)
            wm_mode = "text"
        elif getattr(upload, "filename", ""):
            watermark.save_file(db, upload.filename, await upload.read(watermark.MAX_BYTES + 1))
            wm_mode = "file"  # neue Datei hochgeladen → auch verwenden
        watermark.save_options(db, wm_mode, wm_volume)
        levels = {}
        for key in music_mix.LEVELS:
            if form.get(key) not in (None, ""):
                try:
                    levels[key] = int(str(form.get(key)))
                except ValueError as e:
                    raise ValueError("Hintergrundmusik: bitte ganze Prozentwerte angeben") from e
        music_mix.save_levels(db, levels)
    except ValueError as e:
        return _render_settings(request, user, db, error=str(e), mail_default_to=mail_default_to)
    save_settings(db, values)
    return redirect("/admin/settings", "Einstellungen gespeichert.", request)


@router.get("/settings/watermark-audio")
def watermark_audio(user=Depends(admin_only), db: Session = Depends(get_db)):
    """Eigene Wasserzeichen-Datei zum Vorhören im Admin."""
    path = watermark.get_config(db)["path"]
    if path is None:
        raise HTTPException(404)
    media = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac"}
    return Response(path.read_bytes(), media_type=media.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/prices", response_class=HTMLResponse)
def prices_form(request: Request, user=Depends(section_page("prices")), db: Session = Depends(get_db)):
    return render(request, "admin/prices.html", user=user, cfg=get_settings(db),
                  error=None, flash=pop_flash(request), has_packages=_active_packages(db))


@router.get("/wheel", response_class=HTMLResponse)
def wheel_form(request: Request, user=Depends(section_page("wheel")), db: Session = Depends(get_db)):
    return _render_wheel(request, user, db)


def _render_wheel(request: Request, user, db: Session, error=None, cfg=None):
    cfg = cfg or wheel.get_config(db)
    rows = cfg.segments + [{"label": "", "percent": 0, "weight": 0}] * (wheel.MAX_SEGMENTS - len(cfg.segments))
    return render(request, "admin/wheel.html", user=user, wheel=cfg, rows=rows, error=error,
                  flash=None if error else pop_flash(request), max_percent=wheel.MAX_PERCENT,
                  modes=wheel.MODES, popup_steps=wheel.POPUP_STEPS, styles=wheel.STYLES)


@router.post("/wheel")
async def wheel_save(request: Request, user=Depends(section_page("wheel")), db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    segments = [{"label": l, "percent": p, "weight": w} for l, p, w in
                zip(form.getlist("label"), form.getlist("percent"), form.getlist("weight"))]
    try:
        hours = int(str(form.get("valid_hours") or "72"))
        wheel.save_config(db, form.get("enabled") == "on", form.get("stackable") == "on", hours, segments,
                          str(form.get("mode", "inline")), str(form.get("popup_step", "4")),
                          str(form.get("style", "wheel")))
    except ValueError as e:
        msg = str(e) if "invalid literal" not in str(e) else "Gültigkeit: bitte eine ganze Zahl (Stunden) angeben"
        draft = wheel.WheelConfig(enabled=form.get("enabled") == "on", stackable=form.get("stackable") == "on",
                                  valid_hours=72, segments=[s for s in segments if str(s["label"]).strip()][:wheel.MAX_SEGMENTS],
                                  mode=str(form.get("mode", "inline")), popup_step=int(form.get("popup_step", "4") or 4),
                                  style=str(form.get("style", "wheel")))
        return _render_wheel(request, user, db, error=msg, cfg=draft)
    return redirect("/admin/wheel", "Glücksrad gespeichert.", request)


def _active_packages(db: Session) -> int:
    return db.query(Package).filter(Package.active.is_(True)).count()


@router.post("/prices")
def prices_save(request: Request, user=Depends(section_page("prices")), db: Session = Depends(get_db),
                csrf: str = Form(""), min_order: str = Form("0"), currency: str = Form("EUR"),
                ad_tax_rate: str = Form("0"), studio_price: str = Form("349"), ad_tax_in_vat_base: str = Form(""),
                individual_booking: str = Form(""), booking_lead_days: str = Form("3")):
    check_csrf(request, csrf)
    try:
        values = {
            "ad_tax_rate_bp": int(_parse_decimal(ad_tax_rate or "0", "Werbeabgabe") * 100),
            "ad_tax_in_vat_base": ad_tax_in_vat_base == "on",
            "min_order_cent": int(_parse_decimal(min_order or "0", "Mindestbestellwert") * 100),
            "studio_price_cent": int(_parse_decimal(studio_price or "0", "Preis Studiospot") * 100),
            "currency": currency.strip().upper()[:3] or "EUR",
            "individual_booking": individual_booking == "on",
            "booking_lead_days": int(_parse_decimal(booking_lead_days or "0", "Vorlaufzeit")),
        }
        if not 0 <= values["booking_lead_days"] <= 60:
            raise ValueError("Vorlaufzeit: 0 bis 60 Tage")
        if not 0 <= values["ad_tax_rate_bp"] <= 10_000:
            raise ValueError("Werbeabgabe: zwischen 0 und 100 %")
        if values["min_order_cent"] < 0 or values["studio_price_cent"] < 0:
            raise ValueError("Preise dürfen nicht negativ sein")
    except ValueError as e:
        return render(request, "admin/prices.html", user=user, cfg=get_settings(db), error=str(e), flash=None,
                      has_packages=_active_packages(db))
    save_settings(db, values)
    return redirect("/admin/prices", "Preise gespeichert.", request)


@router.get("/account", response_class=HTMLResponse)
def account_form(request: Request, user=Depends(admin_page)):
    return render(request, "admin/account.html", user=user, flash=pop_flash(request), error=None)


@router.post("/password")
def change_password(request: Request, user=Depends(admin_page), db: Session = Depends(get_db),
                    csrf: str = Form(""), current: str = Form(...), new: str = Form(...)):
    check_csrf(request, csrf)
    if not verify_password(current, user.password_hash):
        return redirect("/admin/account", "Aktuelles Passwort ist falsch.", request)
    if len(new) < 10:
        return redirect("/admin/account", "Neues Passwort muss mindestens 10 Zeichen haben.", request)
    user.password_hash = hash_password(new)
    db.commit()
    return redirect("/admin/account", "Passwort geändert.", request)


# --------------------------------------------------------------------------- Benutzer (nur Admin)

_USERNAME_RE = re.compile(r"[A-Za-z0-9._@-]{3,80}")


def _render_users(request: Request, user, db: Session, error=None, values=None):
    users = db.query(AdminUser).order_by(AdminUser.username).all()
    return render(request, "admin/users.html", user=user, users=users, error=error,
                  values=values or {"role": "sales"}, flash=None if error else pop_flash(request))


def _admin_count(db: Session) -> int:
    return db.query(AdminUser).filter(AdminUser.role == "admin").count()


@router.get("/users", response_class=HTMLResponse)
def users_list(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    return _render_users(request, user, db)


@router.post("/users/new")
def user_create(request: Request, user=Depends(admin_only), db: Session = Depends(get_db),
                csrf: str = Form(""), username: str = Form(""), password: str = Form(""), role: str = Form("sales")):
    check_csrf(request, csrf)
    username = username.strip()
    values = {"username": username, "role": role}
    if not _USERNAME_RE.fullmatch(username):
        return _render_users(request, user, db, "Benutzername: 3–80 Zeichen, nur Buchstaben, Ziffern und . _ @ -", values)
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        return _render_users(request, user, db, f"Den Benutzer „{username}“ gibt es schon.", values)
    if role not in ROLES:
        return _render_users(request, user, db, "Bitte eine Rolle wählen.", values)
    if len(password) < 10:
        return _render_users(request, user, db, "Passwort muss mindestens 10 Zeichen haben.", values)
    db.add(AdminUser(username=username, password_hash=hash_password(password), role=role))
    db.commit()
    return redirect("/admin/users", f"Benutzer „{username}“ ({ROLES[role]}) angelegt.", request)


@router.post("/users/{user_id}")
def user_update(user_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db),
                csrf: str = Form(""), role: str = Form(""), password: str = Form("")):
    check_csrf(request, csrf)
    target = db.get(AdminUser, user_id)
    if target is None:
        raise HTTPException(404)
    if role not in ROLES:
        return _render_users(request, user, db, "Bitte eine Rolle wählen.")
    if role != "admin" and target.role == "admin" and _admin_count(db) <= 1:
        return _render_users(request, user, db, "Es muss mindestens ein Administrator bleiben.")
    if password and len(password) < 10:
        return _render_users(request, user, db, "Neues Passwort muss mindestens 10 Zeichen haben.")
    target.role = role
    if password:
        target.password_hash = hash_password(password)
    db.commit()
    msg = f"„{target.username}“ gespeichert" + (" – neues Passwort gesetzt." if password else ".")
    return redirect("/admin/users", msg, request)


@router.post("/users/{user_id}/delete")
def user_delete(user_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db),
                csrf: str = Form("")):
    check_csrf(request, csrf)
    target = db.get(AdminUser, user_id)
    if target is None:
        raise HTTPException(404)
    if target.id == user.id:
        return _render_users(request, user, db, "Du kannst dich nicht selbst löschen.")
    if target.role == "admin" and _admin_count(db) <= 1:
        return _render_users(request, user, db, "Der letzte Administrator kann nicht gelöscht werden.")
    db.delete(target)
    db.commit()
    return redirect("/admin/users", f"Benutzer „{target.username}“ gelöscht.", request)


# --------------------------------------------------------------------------- Anfragen

@router.get("/requests", response_class=HTMLResponse)
def requests_list(request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.query(QuoteRequest).order_by(QuoteRequest.created_at.desc()).all()
    return render(request, "admin/requests.html", user=user, rows=rows, flash=pop_flash(request))


STATUSES = ["neu", "in_bearbeitung", "angebot_versendet", "gebucht", "abgelehnt"]


def _get_request(db: Session, req_id: int) -> QuoteRequest:
    row = db.get(QuoteRequest, req_id)
    if row is None:
        raise HTTPException(404)
    return row


def _audio_voice(db: Session, row: QuoteRequest) -> Voice | None:
    """Stimme der Anfrage, wenn sich daraus ein Spot erzeugen lässt (Text, KI-Stimme, ElevenLabs)."""
    prod = (row.configuration or {}).get("production") or {}
    voice = db.get(Voice, prod.get("voice_id") or 0)
    script = (row.brief or {}).get("script", "").strip()
    if not script or voice is None or not voice.has_tts or not audio.tts_enabled():
        return None
    return voice


async def _render_request_audio(db: Session, row: QuoteRequest, kind: str) -> tuple[str, bytes]:
    """Ohne Wasserzeichen, 48 kHz Stereo 24 Bit: kind="spot" → fertiger Spot (gemastert auf die
    Ziel-Lautheit), kind="voice" → nur die Sprache. Liefert (Dateiname, WAV-Daten)."""
    from .public import render_spot, render_voice, tts_settings

    voice = _audio_voice(db, row)
    if voice is None:
        raise audio.AudioError("Für diese Anfrage kann kein Spot erzeugt werden (Text, KI-Stimme oder ElevenLabs fehlt).", 404)
    prod = (row.configuration or {}).get("production") or {}
    script = row.brief["script"].strip()
    # gleiche Einstellungen wie bei der Hörprobe des Kunden (Tonalität, Spotlänge)
    tonality = db.query(Tonality).filter_by(name=(row.brief or {}).get("tonality", "")).first()
    length = db.get(SpotLength, prod.get("spot_length_id") or 0)
    settings_ = tts_settings(voice, tonality, script, length.seconds if length else None)
    if kind == "spot":
        samples = await render_spot(db, voice, script, prod.get("music_style_id"), watermark=False,
                                    settings_=settings_)
    else:
        samples = await render_voice(voice, script, settings_)
    name = f"onaircraft-{'spot' if kind == 'spot' else 'sprache'}-{row.id}.wav"
    return name, audio.to_wav(samples, bits=24)


def _default_mail(row: QuoteRequest) -> dict:
    who = row.company or row.customer_name
    script = (row.brief or {}).get("script", "").strip()
    q = row.quote or {}
    period = ""
    if q.get("period_start"):
        start, end = (date.fromisoformat(str(q[k])) for k in ("period_start", "period_end"))
        period = f"Zeitraum: {start:%d.%m.%Y} – {end:%d.%m.%Y} ({q.get('period_days')} Tage)\n"
    body = (f"Hallo,\n\nanbei die Unterlagen zur Radiospot-Anfrage Nr. {row.id} von {who}.\n" + period
            + (f"\nSpot-Text:\n{script}\n" if script else "")
            + "\nViele Grüße\nonaircraft")
    return {"subject": f"Radiospot-Anfrage Nr. {row.id} – {who}", "body": body}


def _render_detail(request: Request, user, db: Session, row: QuoteRequest, mail_values: dict | None = None,
                   error: str | None = None):
    audio_possible = _audio_voice(db, row) is not None
    mail = mail_values or {"to": mailer.default_recipient(db), **_default_mail(row),
                           "pdf": True, "spot": audio_possible, "voice": audio_possible}
    return render(request, "admin/request_detail.html", user=user, row=row, statuses=STATUSES,
                  flash=None if error else pop_flash(request), error=error, mail=mail,
                  mail_enabled=mailer.is_configured(), audio_possible=audio_possible)


@router.get("/requests/{req_id}", response_class=HTMLResponse)
def request_detail(req_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    return _render_detail(request, user, db, _get_request(db, req_id))


@router.get("/requests/{req_id}/audio/{kind}")
async def request_audio(req_id: int, kind: str, request: Request, user=Depends(admin_only),
                        db: Session = Depends(get_db)):
    if kind not in ("spot", "voice"):
        raise HTTPException(404)
    try:
        name, data = await _render_request_audio(db, _get_request(db, req_id), kind)
    except audio.AudioError as e:
        raise HTTPException(e.status, str(e)) from e
    return Response(data, media_type="audio/wav", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/requests/{req_id}/email")
async def request_email(req_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    """PDF und/oder Audiodateien (ohne Wasserzeichen) mit eigenem Text per E-Mail verschicken."""
    from .public import pdf_bytes

    form = await request.form()
    check_csrf(request, form.get("csrf"))
    row = _get_request(db, req_id)
    values = {"to": str(form.get("to", "")), "subject": str(form.get("subject", "")).strip(),
              "body": str(form.get("body", "")).replace("\r\n", "\n"),
              "pdf": form.get("pdf") == "on", "spot": form.get("spot") == "on", "voice": form.get("voice") == "on"}
    try:
        to = mailer.parse_recipients(values["to"])
        if not values["subject"]:
            raise mailer.MailError("Bitte einen Betreff angeben.")
        attachments: list[tuple[str, bytes, str]] = []
        if values["pdf"]:
            attachments.append((f"onaircraft-anfrage-{row.id}.pdf", pdf_bytes(row, db), "application/pdf"))
        for kind in ("spot", "voice"):
            if values[kind]:
                try:
                    name, data = await _render_request_audio(db, row, kind)
                except audio.AudioError as e:
                    raise mailer.MailError(f"Audiodatei konnte nicht erzeugt werden: {e}") from e
                attachments.append((name, data, "audio/wav"))
        msg = mailer.build_message(to, values["subject"], values["body"], attachments)
        await run_in_threadpool(mailer.send, msg)
    except mailer.MailError as e:
        return _render_detail(request, user, db, row, mail_values=values, error=f"E-Mail nicht gesendet: {e}")
    size_mb = sum(len(d) for _, d, _ in attachments) / 1024 / 1024
    row.mail_log = [*(row.mail_log or []), {
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "to": to, "subject": values["subject"],
        "attachments": [n for n, _, _ in attachments], "by": user.username}]
    db.commit()
    files = ", ".join(n for n, _, _ in attachments) or "keine Anhänge"
    return redirect(f"/admin/requests/{req_id}",
                    f"E-Mail an {', '.join(to)} gesendet ({files}; {size_mb:.1f} MB).", request)


@router.get("/requests/{req_id}/pdf")
def request_pdf(req_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db)):
    from .public import _pdf_response

    return _pdf_response(_get_request(db, req_id), db)


@router.post("/requests/{req_id}/status")
def request_status(req_id: int, request: Request, user=Depends(admin_only), db: Session = Depends(get_db),
                   csrf: str = Form(""), status: str = Form(...)):
    check_csrf(request, csrf)
    row = db.get(QuoteRequest, req_id)
    if row is None:
        raise HTTPException(404)
    if status not in STATUSES:
        raise HTTPException(400, "Ungültiger Status")
    row.status = status
    db.commit()
    return redirect(f"/admin/requests/{req_id}", "Status aktualisiert.", request)


# --------------------------------------------------------------------------- Generisches CRUD

def _entity(slug: str, user=None) -> Entity:
    if slug not in ENTITIES:
        raise HTTPException(404)
    if user is not None and not can(user, slug):
        raise _Forbidden(user)
    return ENTITIES[slug]


@router.get("/{slug}", response_class=HTMLResponse)
def entity_list(slug: str, request: Request, user=Depends(admin_page), db: Session = Depends(get_db)):
    e = _entity(slug, user)
    objs = db.query(e.model).order_by(e.model.sort_order, e.model.id).all()
    cols = [f for f in e.fields if f.in_list]
    options = {f.name: f.options(db) for f in cols if f.options}
    rows = [(o, [_list_value(e, f, o, options) for f in cols]) for o in objs]
    return render(request, "admin/list.html", user=user, e=e, cols=cols, rows=rows, flash=pop_flash(request))


def _render_form(request: Request, user, e: Entity, db: Session, obj=None, values=None, error=None):
    values = values or {f.name: _form_value(e, f, obj) for f in e.fields}
    options = {f.name: f.options(db) for f in e.fields if f.options}
    return render(request, "admin/form.html", user=user, e=e, obj=obj, values=values,
                  options=options, error=error)


@router.get("/{slug}/new", response_class=HTMLResponse)
def entity_new(slug: str, request: Request, user=Depends(admin_page), db: Session = Depends(get_db)):
    return _render_form(request, user, _entity(slug, user), db)


@router.get("/{slug}/{item_id}", response_class=HTMLResponse)
def entity_edit(slug: str, item_id: int, request: Request, user=Depends(admin_page), db: Session = Depends(get_db)):
    e = _entity(slug, user)
    obj = db.get(e.model, item_id)
    if obj is None:
        raise HTTPException(404)
    return _render_form(request, user, e, db, obj=obj)


async def _store_music(upload) -> str:
    """Musik-Upload prüfen (lesbar, Format, Größe) und unter media/music speichern."""
    ext = Path(upload.filename).suffix.lower()
    if ext not in audio.MUSIC_EXTENSIONS:
        raise ValueError("Bitte eine MP3-, WAV-, OGG- oder FLAC-Datei hochladen.")
    content = await upload.read()
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("Die Datei ist größer als 20 MB.")
    try:
        audio.decode(content)
    except audio.AudioError as e:
        raise ValueError("Die Datei konnte nicht als Audio gelesen werden.") from e
    name = f"{uuid.uuid4().hex}{ext}"
    audio.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (audio.MUSIC_DIR / name).write_bytes(content)
    return name


async def _save(slug: str, request: Request, user, db: Session, item_id: int | None):
    e = _entity(slug, user)
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    obj = db.get(e.model, item_id) if item_id else None
    if item_id and obj is None:
        raise HTTPException(404)
    file_fields = [f for f in e.fields if f.type == "file"]
    raw = {f.name: form.getlist(f.name) if f.type == "multi" else form.get(f.name)
           for f in e.fields if f.type != "file"}
    try:
        data = e.finalize({f.name: f.parse(raw[f.name]) for f in e.fields if f.type != "file"})
        for f in file_fields:
            upload = form.get(f.name)
            if getattr(upload, "filename", ""):
                data[f.name] = await _store_music(upload)
    except ValueError as err:
        values = {k: (v if isinstance(v, list) else v or "") for k, v in raw.items()}
        values.update({f.name: getattr(obj, f.name, "") if obj else "" for f in file_fields})
        return _render_form(request, user, e, db, obj=obj, values=values, error=str(err))
    replaced = [getattr(obj, f.name) for f in file_fields if obj is not None and f.name in data and getattr(obj, f.name)]
    if obj is None:
        obj = e.model(**data)
        db.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
    db.commit()
    for name in replaced:  # ersetzte Musikdatei entfernen
        (audio.MUSIC_DIR / name).unlink(missing_ok=True)
    return redirect(f"/admin/{slug}", f"{e.singular} gespeichert.", request)


@router.post("/{slug}/new")
async def entity_create(slug: str, request: Request, user=Depends(admin_page), db: Session = Depends(get_db)):
    return await _save(slug, request, user, db, None)


@router.post("/{slug}/{item_id}")
async def entity_update(slug: str, item_id: int, request: Request, user=Depends(admin_page),
                        db: Session = Depends(get_db)):
    return await _save(slug, request, user, db, item_id)


@router.post("/{slug}/{item_id}/delete")
def entity_delete(slug: str, item_id: int, request: Request, user=Depends(admin_page),
                  db: Session = Depends(get_db), csrf: str = Form("")):
    e = _entity(slug, user)
    check_csrf(request, csrf)
    obj = db.get(e.model, item_id)
    if obj is None:
        raise HTTPException(404)
    db.delete(obj)
    db.commit()
    return redirect(f"/admin/{slug}", f"{e.singular} gelöscht.", request)
