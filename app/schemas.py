"""Pydantic-Schemas für die öffentliche API und die Admin-API."""
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import DiscountKind, DiscountScope


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- Katalog (öffentlich)

class StationPublic(ORMModel):
    id: int
    name: str
    region: str
    description: str
    price_per_second_cent: int
    kind: str
    coverage_ids: list[int] = Field(default_factory=list)
    map_color: str = ""


class CoverageAreaPublic(ORMModel):
    id: int
    name: str
    technology: str
    states: list[str]
    center_lat: float | None
    center_lon: float | None
    radius_km: int
    reach_text: str
    color: str = ""


class TimeSlotPublic(ORMModel):
    id: int
    name: str
    start_time: str
    end_time: str
    price_factor_bp: int


class SpotLengthPublic(ORMModel):
    id: int
    seconds: int
    label: str


class NamedPublic(ORMModel):
    id: int
    name: str


class VoicePublic(ORMModel):
    id: int
    name: str
    tag: str
    tier: str
    sample_url: str
    has_tts: bool
    pitch_bp: int
    rate_bp: int


class MusicStylePublic(ORMModel):
    id: int
    name: str
    audio_url: str


class AddOnPublic(ORMModel):
    id: int
    name: str
    description: str
    price_cent: int
    requires_studio: bool


class PackagePublic(ORMModel):
    id: int
    name: str
    badge: str
    description: str
    price_cent: int
    spots: int
    max_seconds: int
    includes_studio: bool
    coverage_ids: list[int] = Field(default_factory=list)
    station_ids: list[int] = Field(default_factory=list)
    station_mode: str = "choose"


class CountryPublic(ORMModel):
    code: str
    name: str
    reverse_charge: bool


class Catalog(BaseModel):
    currency: str
    countries: list[CountryPublic]
    ad_tax_rate_bp: int
    min_order_cent: int
    studio_price_cent: int
    ai_enabled: bool = Field(description="KI-Textvorschlag serverseitig konfiguriert")
    audio_tags: bool = Field(description="KI-Stimme versteht Regieanweisungen wie [excited] (Eleven v4/v3)")
    tts_enabled: bool = Field(description="KI-Stimme (ElevenLabs) serverseitig konfiguriert")
    occasions: list[NamedPublic]
    tonalities: list[NamedPublic]
    language_styles: list[NamedPublic]
    voices: list[VoicePublic]
    music_styles: list[MusicStylePublic]
    stations: list[StationPublic]
    time_slots: list[TimeSlotPublic]
    spot_lengths: list[SpotLengthPublic]
    addons: list[AddOnPublic]
    packages: list[PackagePublic] = Field(default_factory=list)
    individual_booking: bool = Field(default=True, description="„Individuell“ (Buchung nach Sekunden) verfügbar")
    coverage_areas: list[CoverageAreaPublic] = Field(default_factory=list)


# --------------------------------------------------------------------------- Preisberechnung

class QuoteItemIn(BaseModel):
    station_id: int
    time_slot_id: int
    spot_length_id: int
    spots: int = Field(ge=1, le=10_000, description="Anzahl Ausstrahlungen")


# Formatprüfung der UID-Nummer je Rechnungsland (Regex, Beispiel); andere Länder: Länderkürzel + 2–13 Zeichen
VAT_ID_FORMATS = {
    "AT": (r"ATU\d{8}", "ATU12345678"),
    "DE": (r"DE\d{9}", "DE123456789"),
    "CH": (r"CHE\d{9}(MWST|TVA|IVA)?", "CHE-123.456.789 MWST"),
    "GR": (r"EL\d{9}", "EL123456789"),
    "GB": (r"GB(\d{9}|\d{12})", "GB123456789"),
}


def vat_id_format(country: str) -> tuple[str, str]:
    return VAT_ID_FORMATS.get(country, (rf"{country}[A-Z0-9]{{2,13}}", f"{country}…"))


class ProductionIn(BaseModel):
    """Text & Hörbeispiel sind gratis; studio=True bestellt den Studiospot mit echtem Sprecher."""
    spot_length_id: int
    voice_id: int
    music_style_id: int | None = None
    studio: bool = False


class QuoteIn(BaseModel):
    production: ProductionIn | None = None
    package_id: int | None = Field(default=None, description="Komplettpaket zum Pauschalpreis")
    package_station_id: int | None = Field(default=None, description="Gewählter Sender, wenn das Paket eine Senderwahl hat")
    items: list[QuoteItemIn] = Field(default_factory=list, max_length=50, description="Schaltung (optional)")
    addon_ids: list[int] = Field(default_factory=list, max_length=50)
    promo_code: str | None = Field(default=None, max_length=60)
    country: str = Field(default="AT", pattern=r"^[A-Z]{2}$", description="Rechnungsland (ISO-Code) – bestimmt die MwSt.")
    vat_id: str | None = Field(default=None, max_length=20,
                               description="UID-Nummer; bei Ländern mit Reverse Charge → Nettorechnung")

    @field_validator("vat_id")
    @classmethod
    def _normalize_vat_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = re.sub(r"[\s.\-]", "", v).upper()
        return v or None

    @model_validator(mode="after")
    def _check(self):
        if self.production is None and not self.items and self.package_id is None:
            raise ValueError("Bitte Produktion, Komplettpaket und/oder Schaltung angeben")
        if self.vat_id:
            pattern, example = vat_id_format(self.country)
            if not re.fullmatch(pattern, self.vat_id):
                raise ValueError(f"UID-Nummer ungültig – Format für {self.country}: {example}")
        return self


class QuoteProduction(BaseModel):
    seconds: int
    voice: str
    music: str | None
    studio: bool
    total_cent: int
    in_package: bool = Field(default=False, description="Studiospot ist im Komplettpaket enthalten")


class QuotePackage(BaseModel):
    name: str
    article_no: str = ""
    description: str
    station: str = Field(default="", description="Gewählter bzw. enthaltene Sender, z. B. „Radio Energy + Radio Nostalgie“")
    coverage: str = ""
    spots: int
    includes_studio: bool
    price_cent: int


class QuoteLine(BaseModel):
    station: str
    kind: str = "radio"
    coverage: str = Field(default="", description="Sendegebiete, z. B. „UKW Wien · DAB+ National“")
    time_slot: str
    seconds: int
    spots: int
    unit_price_cent: int
    total_cent: int


class QuoteAddOn(BaseModel):
    name: str
    price_cent: int


class AppliedDiscount(BaseModel):
    name: str
    description: str
    amount_cent: int


class QuoteOut(BaseModel):
    currency: str
    country: str
    country_name: str
    vat_id: str | None = None
    reverse_charge: bool = Field(description="Nettorechnung: Steuerschuld geht auf den Leistungsempfänger über")
    production: QuoteProduction | None
    package: QuotePackage | None = None
    lines: list[QuoteLine]
    addons: list[QuoteAddOn]
    total_spots: int
    production_subtotal_cent: int
    package_subtotal_cent: int = 0
    airtime_subtotal_cent: int
    addons_subtotal_cent: int
    subtotal_cent: int
    discounts: list[AppliedDiscount]
    discount_total_cent: int
    net_cent: int = Field(description="Netto nach Rabatten, ohne Werbeabgabe")
    ad_tax_rate_bp: int
    ad_tax_base_cent: int = Field(description="Bemessungsgrundlage Werbeabgabe (Sendezeit nach Rabatten)")
    ad_tax_cent: int
    vat_rate_bp: int
    vat_base_cent: int
    vat_cent: int
    gross_cent: int
    promo_code_status: str | None = Field(
        description="null = kein Code, 'applied' = angewendet, 'invalid' = unbekannt/Bedingung nicht erfüllt, "
        "'superseded' = gültig, aber ein besserer Rabatt wurde gewählt"
    )
    meets_minimum_order: bool
    min_order_cent: int


class BriefIn(BaseModel):
    """Inhaltliche Angaben zum Spot aus dem Konfigurator."""
    occasion: str = Field(default="", max_length=120)
    firma: str = Field(default="", max_length=160)
    tonality: str = Field(default="", max_length=120)
    language_style: str = Field(default="", max_length=120)
    botschaft: str = Field(default="", max_length=2000)
    cta: str = Field(default="", max_length=500)
    script: str = Field(default="", max_length=5000)


class QuoteRequestIn(BaseModel):
    configuration: QuoteIn
    brief: BriefIn = Field(default_factory=BriefIn)
    customer_name: str = Field(min_length=1, max_length=160)
    company: str = Field(default="", max_length=160)
    street: str = Field(min_length=1, max_length=200, description="Straße und Hausnummer")
    zip_code: str = Field(min_length=3, max_length=20)
    city: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=60)
    message: str = Field(default="", max_length=5000)
    accept_terms: bool = Field(default=False, description="AGB akzeptiert (Pflicht)")
    accept_privacy: bool = Field(default=False, description="Datenschutzerklärung akzeptiert (Pflicht)")

    @model_validator(mode="after")
    def _consent(self):
        if not self.accept_terms:
            raise ValueError("Bitte den AGB zustimmen.")
        if not self.accept_privacy:
            raise ValueError("Bitte der Datenschutzerklärung zustimmen.")
        return self

    @field_validator("customer_name", "company", "street", "zip_code", "city", "phone", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ScriptRequestIn(BaseModel):
    occasion_id: int
    spot_length_id: int
    tonality_id: int
    language_style_id: int
    firma: str = Field(min_length=1, max_length=160)
    botschaft: str = Field(min_length=1, max_length=2000)
    cta: str = Field(min_length=1, max_length=500)


class LegalTextOut(ORMModel):
    key: str
    title: str
    body: str
    updated_at: datetime
    version: str


class ScriptOut(BaseModel):
    script: str


class DemoAudioIn(BaseModel):
    voice_id: int
    music_style_id: int | None = None
    spot_length_id: int | None = None
    tonality_id: int | None = None
    script: str = Field(min_length=1, max_length=1000)


class QuoteRequestCreated(BaseModel):
    id: int
    quote: QuoteOut
    pdf_url: str = Field(description="Signierter Link zur PDF-Kostenaufstellung")


# --------------------------------------------------------------------------- Admin-API

class StationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region: str = ""
    description: str = ""
    price_per_second_cent: int = Field(ge=0)
    kind: Literal["radio", "stream"] = "radio"
    ad_tax_applies: bool = True
    coverage_ids: list[int] = Field(default_factory=list)
    map_color: str = Field(default="", pattern=r"^$|^#[0-9a-fA-F]{6}$")
    active: bool = True
    sort_order: int = 0


class StationOut(StationIn, ORMModel):
    id: int


class TimeSlotIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    start_time: str = Field(default="", pattern=r"^$|^([01]\d|2[0-4]):[0-5]\d$")
    end_time: str = Field(default="", pattern=r"^$|^([01]\d|2[0-4]):[0-5]\d$")
    price_factor_bp: int = Field(default=10_000, ge=0)
    active: bool = True
    sort_order: int = 0


class TimeSlotOut(TimeSlotIn, ORMModel):
    id: int


class SpotLengthIn(BaseModel):
    seconds: int = Field(ge=1, le=300)
    label: str = ""
    active: bool = True
    sort_order: int = 0


class SpotLengthOut(SpotLengthIn, ORMModel):
    id: int


class NamedIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    active: bool = True
    sort_order: int = 0


class NamedOut(NamedIn, ORMModel):
    id: int


class TonalityIn(NamedIn):
    stability_bp: int | None = Field(default=None, ge=0, le=10_000)
    style_bp: int | None = Field(default=None, ge=0, le=10_000)
    speed_bp: int | None = Field(default=None, ge=5_000, le=15_000)
    delivery_hint: str = Field(default="", max_length=255)


class TonalityOut(TonalityIn, ORMModel):
    id: int


class CountryIn(NamedIn):
    code: str = Field(pattern=r"^[A-Z]{2}$")
    vat_rate_bp: int = Field(default=2000, ge=0, le=10_000)
    reverse_charge: bool = True


class CountryOut(CountryIn, ORMModel):
    id: int


class LanguageStyleIn(NamedIn):
    instruction: str = ""


class LanguageStyleOut(LanguageStyleIn, ORMModel):
    id: int


class VoiceIn(NamedIn):
    tag: str = ""
    tier: str = "Demo"
    sample_url: str = ""
    elevenlabs_voice_id: str = Field(default="", max_length=64)
    pitch_bp: int = Field(default=10_000, ge=0, le=20_000)
    rate_bp: int = Field(default=10_000, ge=1_000, le=100_000)
    stability_bp: int = Field(default=5_000, ge=0, le=10_000)
    similarity_bp: int = Field(default=7_500, ge=0, le=10_000)
    style_bp: int = Field(default=0, ge=0, le=10_000)
    speed_bp: int = Field(default=10_000, ge=7_000, le=12_000)


class VoiceOut(VoiceIn, ORMModel):
    id: int


class MusicStyleIn(NamedIn):
    gain_bp: int = Field(default=10_000, ge=2_000, le=30_000, description="Lautstärke-Korrektur (10000 = unverändert)")


class MusicStyleOut(MusicStyleIn, ORMModel):
    id: int
    audio_file: str = Field(description="Hochladen über die Admin-Oberfläche")


class AddOnIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    price_cent: int = Field(ge=0)
    requires_studio: bool = False
    active: bool = True
    sort_order: int = 0


class AddOnOut(AddOnIn, ORMModel):
    id: int


class PackageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    article_no: str = Field(default="", max_length=40)
    badge: str = Field(default="", max_length=40)
    description: str = ""
    price_cent: int = Field(ge=0, description="Pauschalpreis netto in Cent")
    spots: int = Field(default=0, ge=0)
    max_seconds: int = Field(default=0, ge=0, le=300)
    includes_studio: bool = False
    ad_tax_applies: bool = True
    airtime_cent: int = Field(default=0, ge=0, description="Basis Werbeabgabe; 0 = gesamter Paketpreis")
    coverage_ids: list[int] = Field(default_factory=list)
    station_ids: list[int] = Field(default_factory=list)
    station_mode: Literal["choose", "all"] = "choose"
    active: bool = True
    sort_order: int = 0


class PackageOut(PackageIn, ORMModel):
    id: int


class CoverageAreaIn(NamedIn):
    technology: Literal["dab", "ukw"] = "ukw"
    states: list[str] = Field(default_factory=list)
    center_lat: float | None = Field(default=None, ge=45.5, le=49.5)
    center_lon: float | None = Field(default=None, ge=9.0, le=17.5)
    radius_km: int = Field(default=0, ge=0, le=300)
    reach_text: str = Field(default="", max_length=255)
    color: str = Field(default="", pattern=r"^$|^#[0-9a-fA-F]{6}$")


class CoverageAreaOut(CoverageAreaIn, ORMModel):
    id: int


class DiscountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    kind: DiscountKind = DiscountKind.percent
    value: int = Field(ge=0, description="percent: Basispunkte (1000 = 10 %), fixed: Cent")
    applies_to: DiscountScope = DiscountScope.airtime
    min_spots: int = Field(default=0, ge=0)
    min_amount_cent: int = Field(default=0, ge=0)
    promo_code: str | None = None
    station_id: int | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    stackable: bool = True
    active: bool = True
    sort_order: int = 0


class DiscountOut(DiscountIn, ORMModel):
    id: int


class SettingsIn(BaseModel):
    company_info: str = Field(default="", max_length=255)
    watermark_text: str = Field(default="Hörprobe von onaircraft", max_length=120)
    watermark_interval_s: int = Field(default=7, ge=3, le=60)
    master_lufs: float = Field(default=-8.0, ge=-30, le=-5)
    master_ceiling_dbtp: float = Field(default=-1.0, ge=-6, le=0)
    ad_tax_rate_bp: int = Field(default=500, ge=0, le=10_000)
    ad_tax_in_vat_base: bool = True
    min_order_cent: int = Field(ge=0)
    studio_price_cent: int = Field(default=34_900, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    individual_booking: bool = Field(default=True, description="Individuelle Buchung nach Sekunden anbieten")


class QuoteRequestOut(ORMModel):
    id: int
    created_at: datetime
    customer_name: str
    company: str
    street: str
    zip_code: str
    city: str
    email: str
    phone: str
    message: str
    configuration: dict
    brief: dict
    consent: dict
    quote: dict
    status: str


class QuoteRequestStatusIn(BaseModel):
    status: str = Field(pattern=r"^(neu|in_bearbeitung|angebot_versendet|gebucht|abgelehnt)$")
