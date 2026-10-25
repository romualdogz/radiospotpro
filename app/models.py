"""Datenbankmodelle.

Geldbeträge werden durchgehend als Integer in Cent gespeichert (keine Rundungsfehler).
Prozentwerte werden in Basispunkten gespeichert: 1000 = 10,00 %.
"""
import enum
import hashlib
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # "admin" = alles, "sales" = Verkaufsleitung (nur Preise, Länder & MwSt.)
    role: Mapped[str] = mapped_column(String(20), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Station(Base):
    """Buchbarer Kanal (Radiosender oder Stream der Energy-Gruppe) – Basis für den Sekundenpreis."""

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price_per_second_cent: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="radio")  # "radio" | "stream"
    # Österreichische Werbeabgabe gilt für Radio, nicht für Online-Streams
    ad_tax_applies: Mapped[bool] = mapped_column(Boolean, default=True)
    coverage_ids: Mapped[list] = mapped_column(JSON, default=list)  # Sendegebiete (CoverageArea.id)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# Bundesländer (Schlüssel wie in app/static/austria-map.json)
STATES = [
    ("burgenland", "Burgenland"), ("kaernten", "Kärnten"), ("niederoesterreich", "Niederösterreich"),
    ("oberoesterreich", "Oberösterreich"), ("salzburg", "Salzburg"), ("steiermark", "Steiermark"),
    ("tirol", "Tirol"), ("vorarlberg", "Vorarlberg"), ("wien", "Wien"),
]


class CoverageArea(Base):
    """Sendegebiet für die Reichweiten-Karte: DAB+ (Bundesländer) oder UKW (Bundesländer und/oder Kreis um den Sender)."""

    __tablename__ = "coverage_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    technology: Mapped[str] = mapped_column(String(10), default="ukw")  # "dab" | "ukw"
    states: Mapped[list] = mapped_column(JSON, default=list)            # Bundesland-Schlüssel, die aufleuchten
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_km: Mapped[int] = mapped_column(Integer, default=0)          # 0 = kein Kreis
    reach_text: Mapped[str] = mapped_column(String(255), default="")    # Hinweis für Kunden
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TimeSlot(Base):
    """Zeitschiene (z. B. Morning Show) mit Preisfaktor auf den Sekundenpreis."""

    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    start_time: Mapped[str] = mapped_column(String(5), default="")  # "06:00"
    end_time: Mapped[str] = mapped_column(String(5), default="")    # "10:00"
    price_factor_bp: Mapped[int] = mapped_column(Integer, default=10000)  # 10000 = Faktor 1,0
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SpotLength(Base):
    __tablename__ = "spot_lengths"

    id: Mapped[int] = mapped_column(primary_key=True)
    seconds: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80), default="")
    # Nicht mehr verwendet (Text & Hörbeispiel sind gratis) – bleibt für bestehende Datenbanken erhalten.
    production_price_cent: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Occasion(Base):
    """Anlass des Spots (Angebot, Neueröffnung, …) – steuert Ton und Aufbau des Skripts."""

    __tablename__ = "occasions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Tonality(Base):
    """Tonalität – steuert Text (KI) und Sprech-Dynamik der KI-Stimme."""

    __tablename__ = "tonalities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # Überschreibt die Werte der Stimme, leer = Wert der Stimme (10000 = 1,0)
    stability_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    style_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Faktor auf das Tempo der Stimme
    # Hinweis an die KI, welche Regieanweisungen passen (nur Eleven v4/v3)
    delivery_hint: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class LanguageStyle(Base):
    """Sprachstil mit Anweisung, die an die KI-Textgenerierung übergeben wird."""

    __tablename__ = "language_styles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    instruction: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Voice(Base):
    """Stimme für das kostenlose Hörbeispiel."""

    __tablename__ = "voices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    tag: Mapped[str] = mapped_column(String(200), default="")      # "warm, vertrauensbildend · weiblich"
    tier: Mapped[str] = mapped_column(String(40), default="Demo")  # Badge
    surcharge_cent: Mapped[int] = mapped_column(Integer, default=0)  # nicht mehr verwendet
    sample_url: Mapped[str] = mapped_column(String(500), default="")  # echte Hörprobe (optional)
    elevenlabs_voice_id: Mapped[str] = mapped_column(String(64), default="")  # KI-Stimme
    # Für die Browser-Sprachausgabe, falls keine Hörprobe hinterlegt ist (10000 = 1,0)
    pitch_bp: Mapped[int] = mapped_column(Integer, default=10000)
    rate_bp: Mapped[int] = mapped_column(Integer, default=10000)
    # ElevenLabs-Einstellungen (10000 = 1,0); Style und Speed nur bei Multilingual v2 / Flash
    stability_bp: Mapped[int] = mapped_column(Integer, default=5000)
    similarity_bp: Mapped[int] = mapped_column(Integer, default=7500)
    style_bp: Mapped[int] = mapped_column(Integer, default=0)
    speed_bp: Mapped[int] = mapped_column(Integer, default=10000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def has_tts(self) -> bool:
        return bool(self.elevenlabs_voice_id)


class MusicStyle(Base):
    __tablename__ = "music_styles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    surcharge_cent: Mapped[int] = mapped_column(Integer, default=0)  # nicht mehr verwendet
    audio_file: Mapped[str] = mapped_column(String(200), default="")  # Dateiname in media/music
    # Lautstärke-Korrektur dieses Stücks (10000 = unverändert, 7000 = leiser, 13000 = lauter)
    gain_bp: Mapped[int] = mapped_column(Integer, default=10_000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def audio_url(self) -> str:
        return f"/media/music/{self.audio_file}" if self.audio_file else ""


class AddOn(Base):
    """Zusatzleistung mit Fixpreis, z. B. Express-Produktion."""

    __tablename__ = "addons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price_cent: Mapped[int] = mapped_column(Integer)
    requires_studio: Mapped[bool] = mapped_column(Boolean, default=False)  # nur mit Studiospot buchbar
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Package(Base):
    """Komplettpaket zum Pauschalpreis (z. B. Sendezeit-Paket, optional inkl. Studiospot)."""

    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    badge: Mapped[str] = mapped_column(String(40), default="")  # z. B. „Beliebt“
    description: Mapped[str] = mapped_column(Text, default="")  # Leistungen, eine pro Zeile
    price_cent: Mapped[int] = mapped_column(Integer)  # Pauschalpreis netto
    spots: Mapped[int] = mapped_column(Integer, default=0)  # Ausstrahlungen gesamt (Info, Mengenrabatte)
    max_seconds: Mapped[int] = mapped_column(Integer, default=0)  # 0 = jede Spotlänge
    includes_studio: Mapped[bool] = mapped_column(Boolean, default=False)
    ad_tax_applies: Mapped[bool] = mapped_column(Boolean, default=True)
    # Anteil Radio-Sendezeit als Basis der Werbeabgabe; 0 = gesamter Paketpreis
    airtime_cent: Mapped[int] = mapped_column(Integer, default=0)
    coverage_ids: Mapped[list] = mapped_column(JSON, default=list)  # Sendegebiete (CoverageArea.id)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def ad_tax_base_cent(self) -> int:
        if not self.ad_tax_applies:
            return 0
        return min(self.airtime_cent or self.price_cent, self.price_cent)


class DiscountKind(str, enum.Enum):
    percent = "percent"
    fixed = "fixed"


class DiscountScope(str, enum.Enum):
    airtime = "airtime"  # nur auf Sendezeit (Mediavolumen)
    production = "production"  # nur auf den Studiospot
    total = "total"      # auf Sendezeit + Zusatzleistungen


class Discount(Base):
    """Rabattregel. Alle gesetzten Bedingungen müssen erfüllt sein."""

    __tablename__ = "discounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[DiscountKind] = mapped_column(Enum(DiscountKind), default=DiscountKind.percent)
    # percent: Basispunkte (1000 = 10 %), fixed: Cent
    value: Mapped[int] = mapped_column(Integer)
    applies_to: Mapped[DiscountScope] = mapped_column(Enum(DiscountScope), default=DiscountScope.airtime)

    # Bedingungen (leer/0 = keine Bedingung)
    min_spots: Mapped[int] = mapped_column(Integer, default=0)
    min_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    promo_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    # stackable=True: wird mit anderen kombinierbaren Rabatten addiert.
    # stackable=False: exklusiv – greift nur, wenn er allein besser ist als alle kombinierbaren zusammen.
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    station: Mapped[Station | None] = relationship()


class Country(Base):
    """Rechnungsland mit MwSt.-Satz. reverse_charge: mit UID-Nummer Nettorechnung (0 %)."""

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(2), unique=True)  # ISO 3166-1, z. B. AT
    name: Mapped[str] = mapped_column(String(120))
    vat_rate_bp: Mapped[int] = mapped_column(Integer, default=2000)  # 2000 = 20 %
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class LegalText(Base):
    """Rechtstexte (AGB, Datenschutz), im Admin bearbeitbar und im Checkout einblendbar."""

    __tablename__ = "legal_texts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)  # "agb" | "datenschutz"
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def version(self) -> str:
        """Kurzer Fingerabdruck des Textstands – wird mit der Zustimmung gespeichert."""
        return hashlib.sha256(f"{self.title}\n{self.body}".encode()).hexdigest()[:12]

    @property
    def is_placeholder(self) -> bool:
        return self.body.startswith(LEGAL_PLACEHOLDER_MARK)


LEGAL_PLACEHOLDER_MARK = "PLATZHALTER"


class Setting(Base):
    """Globale Einstellungen als Key/Value (z. B. MwSt.-Satz)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class QuoteRequest(Base):
    """Angebotsanfrage aus dem Konfigurator."""

    __tablename__ = "quote_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    customer_name: Mapped[str] = mapped_column(String(160))
    company: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(60), default="")
    street: Mapped[str] = mapped_column(String(200), default="")
    zip_code: Mapped[str] = mapped_column(String(20), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    configuration: Mapped[dict] = mapped_column(JSON)
    brief: Mapped[dict] = mapped_column(JSON, default=dict)  # Firma, Botschaft, CTA, Skript …
    # Nachweis der Zustimmung: {"agb": {"accepted_at": …, "version": …}, "datenschutz": {…}}
    consent: Mapped[dict] = mapped_column(JSON, default=dict)
    # versendete E-Mails: [{"sent_at", "to", "subject", "attachments", "by"}]
    mail_log: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="neu")
