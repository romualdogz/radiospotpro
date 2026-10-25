"""Initialdaten: erster Admin-Benutzer und optionale Demo-Produkte (Werte aus der HTML-Vorlage)."""
import shutil

from sqlalchemy.orm import Session

from .audio import MUSIC_DIR
from .config import BASE_DIR, settings
from .models import (
    LEGAL_PLACEHOLDER_MARK, STATES, AddOn, AdminUser, Country, CoverageArea, Package, Discount, LegalText, DiscountKind, DiscountScope, LanguageStyle, MusicStyle, Occasion, SpotLength,
    Setting, Station, TimeSlot, Tonality, Voice,
)
from .security import hash_password


def ensure_admin(db: Session) -> None:
    if db.query(AdminUser).count() == 0:
        db.add(AdminUser(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
        db.commit()


# Rechnungsländer: Code, Name, MwSt. (Basispunkte), Reverse Charge mit UID.
# Standard für alle außer Österreich/Deutschland: österreichische USt. (20 %), mit UID Nettorechnung.
# Bitte mit der Steuerberatung abstimmen und im Admin unter „Länder“ anpassen.
DEFAULT_COUNTRIES = [
    ("AT", "Österreich", 2000, False),
    ("DE", "Deutschland", 1900, True),
    ("CH", "Schweiz", 2000, True),
    ("LI", "Liechtenstein", 2000, True),
    ("IT", "Italien", 2000, True),
    ("BE", "Belgien", 2000, True),
    ("BG", "Bulgarien", 2000, True),
    ("DK", "Dänemark", 2000, True),
    ("EE", "Estland", 2000, True),
    ("FI", "Finnland", 2000, True),
    ("FR", "Frankreich", 2000, True),
    ("GR", "Griechenland", 2000, True),
    ("IE", "Irland", 2000, True),
    ("HR", "Kroatien", 2000, True),
    ("LV", "Lettland", 2000, True),
    ("LT", "Litauen", 2000, True),
    ("LU", "Luxemburg", 2000, True),
    ("MT", "Malta", 2000, True),
    ("NL", "Niederlande", 2000, True),
    ("PL", "Polen", 2000, True),
    ("PT", "Portugal", 2000, True),
    ("RO", "Rumänien", 2000, True),
    ("SE", "Schweden", 2000, True),
    ("SK", "Slowakei", 2000, True),
    ("SI", "Slowenien", 2000, True),
    ("ES", "Spanien", 2000, True),
    ("CZ", "Tschechien", 2000, True),
    ("HU", "Ungarn", 2000, True),
    ("GB", "Vereinigtes Königreich", 2000, True),
    ("CY", "Zypern", 2000, True),
]


def ensure_countries(db: Session) -> None:
    """Legt die Länderliste an, falls noch keine existiert. Übernimmt frühere AT/DE-Sätze aus den Einstellungen."""
    if db.query(Country).count():
        return
    old = {s.key: int(s.value) for s in db.query(Setting).filter(Setting.key.in_(["vat_rate_at_bp", "vat_rate_de_bp"]))}
    for i, (code, name, vat, reverse_charge) in enumerate(DEFAULT_COUNTRIES, start=1):
        vat = old.get(f"vat_rate_{code.lower()}_bp", vat)
        db.add(Country(code=code, name=name, vat_rate_bp=vat, reverse_charge=reverse_charge, sort_order=i))
    db.commit()


LEGAL_DEFAULTS = {
    "agb": "Allgemeine Geschäftsbedingungen",
    "datenschutz": "Datenschutzerklärung",
}


def ensure_legal_texts(db: Session) -> None:
    """Legt AGB und Datenschutz als deutlich markierte Platzhalter an, falls noch nicht vorhanden."""
    existing = {t.key for t in db.query(LegalText)}
    for key, title in LEGAL_DEFAULTS.items():
        if key not in existing:
            db.add(LegalText(key=key, title=title, body=(
                f"{LEGAL_PLACEHOLDER_MARK} – bitte hier den rechtlich geprüften Text „{title}“ einfügen.\n\n"
                "Bitte im Admin unter „Rechtstexte“ ersetzen, bevor der Konfigurator öffentlich genutzt wird.")))
    db.commit()


# Beispiel-Komplettpakete – Preise sind Platzhalter. Sie werden einmalig INAKTIV angelegt und erst
# nach dem Eintragen der echten Preise im Admin (Preise → Komplettpakete) auf „aktiv“ gestellt.
EXAMPLE_PACKAGES = [
    dict(name="Starter Radio Energy", badge="", price_cent=149000, spots=40, max_seconds=30, includes_studio=False,
         description="40 Ausstrahlungen auf Radio Energy Österreich\nTagesprogramm\nLaufzeit 2 Wochen"),
    dict(name="Kombi Radio & Streams", badge="Beliebt", price_cent=299000, airtime_cent=264100, spots=80,
         max_seconds=30, includes_studio=True,
         description="80 Ausstrahlungen auf Radio Energy, Radio Nostalgie und den Energy-Streams\n"
                     "Studiospot mit echtem Sprecher inklusive\nLaufzeit 4 Wochen"),
    dict(name="Premium Morning Show", badge="", price_cent=499000, airtime_cent=464100, spots=120,
         max_seconds=30, includes_studio=True,
         description="120 Ausstrahlungen, davon 40 in der Morning Show\nStudiospot mit echtem Sprecher inklusive\n"
                     "Laufzeit 6 Wochen"),
]


def ensure_example_packages(db: Session) -> None:
    """Legt die Beispielpakete einmalig (inaktiv) an – auch in bestehenden Datenbanken."""
    if db.get(Setting, "example_packages_created") is not None:
        return
    if db.query(Package).count() == 0:
        for i, p in enumerate(EXAMPLE_PACKAGES, start=1):
            db.add(Package(**p, active=False, sort_order=i))
    db.add(Setting(key="example_packages_created", value="1"))
    db.commit()


# Beispiel-Sendegebiete für die Reichweiten-Karte – Radien sind grobe Richtwerte und sollten mit den
# echten Versorgungsgebieten abgeglichen werden (Admin → Schaltung → Sendegebiete).
EXAMPLE_COVERAGE = [
    dict(name="DAB+ National", technology="dab", states=[k for k, _ in STATES],
         reach_text="ganz Österreich – Empfang mit DAB+-Radio (Auto, Küchen- und Smart-Radio)"),
    dict(name="UKW Wien", technology="ukw", states=["wien"], center_lat=48.2082, center_lon=16.3738, radius_km=45,
         reach_text="Wien und Umgebung"),
    dict(name="UKW Salzburg", technology="ukw", states=[], center_lat=47.8095, center_lon=13.0550, radius_km=35,
         reach_text="Stadt Salzburg und Umgebung"),
    dict(name="UKW Innsbruck", technology="ukw", states=[], center_lat=47.2692, center_lon=11.4041, radius_km=30,
         reach_text="Innsbruck und Inntal"),
]
# welche Sender/Beispielpakete welche Gebiete bekommen (nur wenn dort noch nichts eingetragen ist)
EXAMPLE_COVERAGE_LINKS = {
    "stations": {"Radio Energy Österreich": ["DAB+ National", "UKW Wien"]},
    "packages": {"Starter Radio Energy": ["DAB+ National", "UKW Wien"],
                 "Kombi Radio & Streams": ["DAB+ National", "UKW Wien", "UKW Salzburg", "UKW Innsbruck"],
                 "Premium Morning Show": ["DAB+ National", "UKW Wien", "UKW Salzburg", "UKW Innsbruck"]},
}


def ensure_coverage_areas(db: Session) -> None:
    """Legt die Beispiel-Sendegebiete einmalig an und verknüpft sie mit passenden Sendern und Paketen."""
    if db.get(Setting, "coverage_examples_created") is not None:
        return
    if db.query(CoverageArea).count() == 0:
        areas = {}
        for i, a in enumerate(EXAMPLE_COVERAGE, start=1):
            areas[a["name"]] = CoverageArea(**a, sort_order=i)
            db.add(areas[a["name"]])
        db.flush()
        for model, links in ((Station, EXAMPLE_COVERAGE_LINKS["stations"]), (Package, EXAMPLE_COVERAGE_LINKS["packages"])):
            for obj in db.query(model).filter(model.name.in_(list(links))):
                if not obj.coverage_ids:
                    obj.coverage_ids = [areas[n].id for n in links[obj.name]]
    db.add(Setting(key="coverage_examples_created", value="1"))
    db.commit()


# Selbst erzeugte, lizenzfreie Platzhalter-Musik (app/static/demo-music) je Musikrichtung
DEMO_MUSIC = {
    "Corporate / Uplifting": "corporate-uplifting.wav",
    "Elektronisch": "elektronisch.wav",
    "Akustik, warm": "akustik-warm.wav",
}


def attach_demo_music(db: Session) -> None:
    """Hängt die Platzhalter-Musik an gleichnamige Musikrichtungen, die noch keine Datei haben."""
    changed = False
    for style in db.query(MusicStyle).filter(MusicStyle.name.in_(DEMO_MUSIC), MusicStyle.audio_file == ""):
        src = BASE_DIR / "static" / "demo-music" / DEMO_MUSIC[style.name]
        if not src.exists():
            continue
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        target = f"demo-{src.name}"
        shutil.copyfile(src, MUSIC_DIR / target)
        style.audio_file = target
        changed = True
    if changed:
        db.commit()


# Sprech-Dynamik je Tonalität: Stabilität, Style, Tempo-Faktor (10000 = 1,0) und Hinweis für die KI
TONALITY_PRESETS = {
    "seriös & vertrauensvoll": (7000, 1000, 9700, "ruhig, warm und vertrauensvoll – z. B. [warmly], [calm], [reassuring]"),
    "frech & humorvoll": (3500, 5000, 10500, "verschmitzt und verspielt – z. B. [mischievously], [playfully], [laughs]"),
    "emotional": (3500, 4500, 9500, "gefühlvoll und berührend – z. B. [softly], [warmly], [sighs]"),
    "dringend / Aktion": (4000, 4000, 11000, "energiegeladen und drängend – z. B. [excited], [urgently], [enthusiastic]"),
}


def apply_tonality_presets(db: Session) -> None:
    """Trägt die Voreinstellungen bei gleichnamigen Tonalitäten ein, die noch keine Dynamik haben."""
    changed = False
    for t in db.query(Tonality).filter(Tonality.name.in_(TONALITY_PRESETS), Tonality.delivery_hint == "",
                                       Tonality.stability_bp.is_(None)):
        t.stability_bp, t.style_bp, t.speed_bp, t.delivery_hint = TONALITY_PRESETS[t.name]
        changed = True
    if changed:
        db.commit()


def seed_demo_data(db: Session) -> None:
    if db.query(SpotLength).count() > 0:
        return

    def ordered(items):
        for i, item in enumerate(items, start=1):
            item.sort_order = i
        return items

    db.add_all(ordered([Occasion(name=n) for n in
                        ["Angebot / Sale", "Neueröffnung", "Event", "Imagespot", "Saisonal"]]))
    db.add_all(ordered([Tonality(name=n) for n in
                        ["seriös & vertrauensvoll", "frech & humorvoll", "emotional", "dringend / Aktion"]]))
    db.add_all(ordered([
        LanguageStyle(name="Neutrales Hochdeutsch", instruction=(
            "Schreibe in neutralem, standardsprachlichem Hochdeutsch ohne regionale Färbung, ohne Dialekt "
            "und ohne österreichische oder bayerische Sonderausdrücke.")),
        LanguageStyle(name="Österreichisches Deutsch (leicht)", instruction=(
            "Schreibe in Standarddeutsch mit leichtem österreichischem Einschlag (z. B. Jänner, heuer), "
            "aber ohne Dialekt und ohne Mundart.")),
        LanguageStyle(name="Wienerisch / Dialekt",
                      instruction="Schreibe in bewusst wienerischer Umgangssprache mit Dialekt-Einschlag."),
    ]))
    db.add_all(ordered([
        SpotLength(seconds=15, label="15 Sek."),
        SpotLength(seconds=20, label="20 Sek."),
        SpotLength(seconds=30, label="30 Sek."),
    ]))
    db.add_all(ordered([
        # Voice-ID einer ElevenLabs-Standardstimme – im Admin durch eine deutsche Stimme
        # aus der ElevenLabs Voice Library ersetzen.
        Voice(name="Lena", tag="warm, vertrauensbildend · weiblich", tier="Demo",
              elevenlabs_voice_id="EXAVITQu4vr4xnSDxMaL", pitch_bp=11500, rate_bp=9800),
    ]))
    db.add_all(ordered([
        MusicStyle(name="keine"),
        MusicStyle(name="Corporate / Uplifting"),
        MusicStyle(name="Elektronisch"),
        MusicStyle(name="Akustik, warm"),
    ]))
    db.add_all(ordered([
        # Sekundenpreise sind Platzhalter – im Admin unter „Sender“ die echten Tarife eintragen.
        Station(name="Radio Energy Österreich", price_per_second_cent=850),
        Station(name="Radio Nostalgie", price_per_second_cent=700),
        Station(name="Energy Streams", kind="stream", ad_tax_applies=False, price_per_second_cent=300,
                description="Webradio & App-Streams der Energy-Gruppe"),
    ]))
    db.add_all(ordered([
        TimeSlot(name="Morning Show", start_time="06:00", end_time="10:00", price_factor_bp=15000),
        TimeSlot(name="Tagesprogramm", start_time="10:00", end_time="16:00", price_factor_bp=10000),
        TimeSlot(name="Drive Time", start_time="16:00", end_time="19:00", price_factor_bp=12500),
        TimeSlot(name="Abend", start_time="19:00", end_time="24:00", price_factor_bp=6000),
    ]))
    db.add(AddOn(name="Express-Produktion", description="Fertiger Spot innerhalb von 24 Stunden",
                 price_cent=4900, requires_studio=True, sort_order=1))
    db.add_all(ordered([
        Discount(name="Mengenrabatt ab 50 Ausstrahlungen", kind=DiscountKind.percent, value=500,
                 applies_to=DiscountScope.airtime, min_spots=50),
        Discount(name="Neukunden-Code", kind=DiscountKind.percent, value=1000, promo_code="WILLKOMMEN",
                 applies_to=DiscountScope.production, description="10 % auf den Studiospot"),
    ]))
    db.commit()
    attach_demo_music(db)
    apply_tonality_presets(db)
