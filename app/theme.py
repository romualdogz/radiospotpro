"""Design des Konfigurators (Farben & Schriften) – im Admin unter „Design“ einstellbar.

Die Werte liegen in der Settings-Tabelle (Schlüssel theme_*) und werden als /theme.css
ausgeliefert, das nach configurator.css geladen wird und dessen Farben/Schriften überschreibt.
"""
import hashlib
import re
from sqlalchemy.orm import Session

from .models import Setting

# Farben: Schlüssel → (Bezeichnung im Admin, Standardwert aus der onaircraft-Vorlage, Gruppe)
COLORS: dict[str, tuple[str, str, str]] = {
    "page_bg": ("Seitenhintergrund", "#e2001a", "Seite"),
    "page_text": ("Schrift auf der Seite (Überschrift, Logo, Fußzeile)", "#ffffff", "Seite"),
    "logo_accent": ("Logo-Akzent („air“ in onaircraft)", "#0d0d0d", "Seite"),
    "panel_bg": ("Hintergrund Formular", "#ffffff", "Formular"),
    "field_bg": ("Hintergrund Eingabefelder & Karten", "#f4f4f4", "Formular"),
    "line": ("Rahmen & Linien", "#d4d4d4", "Formular"),
    "text": ("Text", "#141414", "Formular"),
    "text_muted": ("Text gedämpft (Hinweise, Beschriftungen)", "#5c5c5c", "Formular"),
    "accent": ("Akzentfarbe (Buttons, Auswahl, Preis)", "#e4002b", "Formular"),
    "accent_soft": ("Akzent hell (Hintergrund gewählter Elemente)", "#fde8ec", "Formular"),
    "accent_2": ("Akzent dunkel (Fokus, Statusmeldungen)", "#c00024", "Formular"),
    "button_text": ("Schrift auf Buttons", "#ffffff", "Formular"),
    "success": ("Rabatte", "#1e7a43", "Formular"),
    "danger": ("Fehlermeldungen", "#c00024", "Formular"),
}

# Google Fonts mit den Schnitten 400–700, lokal mitgeliefert (app/static/fonts, siehe fonts.py);
# "system" = Systemschrift des Geräts
FONTS = [
    "IBM Plex Sans", "Space Grotesk", "Inter", "Roboto", "Open Sans", "Montserrat", "Poppins", "Raleway",
    "Nunito", "Source Sans 3", "DM Sans", "Work Sans", "Manrope", "Barlow", "Rubik", "Outfit",
    "Plus Jakarta Sans", "Sora", "Figtree", "Archivo", "Oswald", "Playfair Display",
]
SYSTEM_FONT = "system"
FONT_DEFAULTS = {"font_body": "IBM Plex Sans", "font_heading": "Space Grotesk"}

# Texte im Kopf des Konfigurators: Schlüssel → (Bezeichnung, Standard, max. Länge)
TEXTS = {
    "hero_title": ("Überschrift", "Ihr Radiospot, angehört, bevor er läuft.", 120),
    "tagline": ("Untertitel oben rechts (auch im PDF)", "sound so(u)lutions — Wien", 80),
    "game_levels": ("Spielmodus: Namen der 4 Level (mit Komma getrennt)",
                    "Newcomer, Sound-Talent, Studio-Star, Radiolegende", 120),
}
HERO_SIZE_DEFAULT, HERO_SIZE_MIN, HERO_SIZE_MAX = 100, 60, 170  # Größe der Überschrift in %

PRESETS: dict[str, dict[str, str]] = {
    "onaircraft Rot (Standard)": {k: v[1] for k, v in COLORS.items()},
    "Dunkel": {
        "page_bg": "#111111", "page_text": "#ffffff", "logo_accent": "#e4002b", "panel_bg": "#1b1b1b",
        "field_bg": "#242424", "line": "#3a3a3a", "text": "#f2f2f2", "text_muted": "#a0a0a0",
        "accent": "#e4002b", "accent_soft": "#3a0d14", "accent_2": "#ff4d5e", "button_text": "#ffffff",
        "success": "#6fd39a", "danger": "#ff6b5e",
    },
    "Hell & neutral": {
        "page_bg": "#f3f4f6", "page_text": "#111827", "logo_accent": "#e4002b", "panel_bg": "#ffffff",
        "field_bg": "#f9fafb", "line": "#d1d5db", "text": "#111827", "text_muted": "#6b7280",
        "accent": "#e4002b", "accent_soft": "#fde8ec", "accent_2": "#b0001f", "button_text": "#ffffff",
        "success": "#15803d", "danger": "#b91c1c",
    },
}

PRESETS["ENERGY Neon"] = {
    "page_bg": "#0e0e12", "page_text": "#ffffff", "logo_accent": "#e6007e", "panel_bg": "#18181d",
    "field_bg": "#222228", "line": "#3a3a45", "text": "#f4f4f6", "text_muted": "#a3a3ae",
    "accent": "#e6007e", "accent_soft": "#3b0b2b", "accent_2": "#ff3fa4", "button_text": "#ffffff",
    "success": "#5fd39a", "danger": "#ff6b6b",
}

# Layout & Anordnung: Schlüssel → (Bezeichnung, {Wert: Beschreibung}, Standard). Wird als CSS-Klasse
# am <body> gesetzt (z. B. lay-steps-side), die Regeln stehen am Ende von configurator.css.
LAYOUT: dict[str, tuple[str, dict[str, str], str]] = {
    "skin": ("Stil", {"classic": "Klassisch – Karte mit Schatten", "neon": "Neon – Leuchtrahmen & Raster",
                      "flat": "Flach – ohne Rahmen", "arcade": "Arcade – Retro-Computerspiel mit Pixelschrift",
                      "esport": "E-Sport – Gaming-Look, Spieler-Seitenleiste mit Missionen",
                      "jumprun": "Jump & Run – Plattform-Spiel mit Wolken, Münzen und ?-Block",
                      "candy": "Candy Pop – bunt, rund, Wackelpudding-Knöpfe",
                      "blackfriday": "Black Friday – Schwarz-Weiß, Laufband, Sale-Look"},
             "classic"),
    "width": ("Breite", {"narrow": "Schmal (880 px)", "wide": "Breit (1200 px)"}, "narrow"),
    "hero": ("Überschrift", {"left": "Groß, linksbündig", "center": "Groß, zentriert",
                             "compact": "Klein", "hidden": "Ausblenden"}, "left"),
    "steps": ("Schritt-Navigation", {"top": "Oben – Senderskala", "dots": "Oben – Punkte mit Namen",
                                     "side": "Seitenleiste links"}, "top"),
    "header": ("Kopfzeile", {"split": "Logo links, Untertitel rechts", "center": "Logo zentriert"}, "split"),
    "caps": ("Schreibweise der Überschriften", {"normal": "Normal", "upper": "GROSSBUCHSTABEN"}, "normal"),
    "wave": ("Wellen-Animation", {"on": "Anzeigen", "off": "Ausblenden"}, "on"),
    "game": ("Spielmodus", {"off": "Aus", "on": "An – Punkte, Level, Erfolge & Konfetti"}, "off"),
}
# Stile mit eigener Überschriften-Schrift (lokal unter app/static/fonts, siehe scripts/fetch_fonts.py)
SKINS_WITH_FONT = {"arcade": "Press Start 2P", "esport": "Oswald", "jumprun": "Bungee", "candy": "Fredoka",
                   "blackfriday": "Anton"}
SKIN_FONTS = {"Press Start 2P": "400", "Bungee": "400", "Fredoka": "400;500;600;700", "Anton": "400"}  # Schrift → verfügbare Schnitte
LAYOUT_DEFAULTS = {f"layout_{k}": v[2] for k, v in LAYOUT.items()}

# Fertige Varianten: Layout (+ optional passende Farbvorlage)
VARIANTS: dict[str, dict] = {
    "Klassisch": {"description": "Wie bisher: schmale Karte, Senderskala oben.", "colors": None,
                  "layout": {}},
    "ENERGY Neon": {"description": "Dunkel mit Magenta-Leuchtrahmen, zentrierte Großbuchstaben, breit.",
                    "colors": "ENERGY Neon",
                    "layout": {"skin": "neon", "width": "wide", "hero": "center", "steps": "dots",
                               "header": "split", "caps": "upper", "wave": "off"}},
    "Studio": {"description": "Breit, Schritte als Seitenleiste, kleine Überschrift.", "colors": None,
               "layout": {"skin": "flat", "width": "wide", "hero": "compact", "steps": "side",
                          "header": "split", "caps": "normal", "wave": "off"}},
    "Spielerisch": {"description": "Spielmodus: Punkte, Level, Erfolge zum Freischalten und Konfetti beim Absenden.",
                    "colors": None,
                    "layout": {"skin": "classic", "width": "narrow", "hero": "center", "steps": "dots",
                               "header": "split", "caps": "normal", "wave": "on", "game": "on"}},
    "Arcade": {"description": "Retro-Computerspiel: Pixelschrift, Neonfarben, Röhrenbildschirm, Spielmodus an.",
               "colors": "Arcade",
               "layout": {"skin": "arcade", "width": "narrow", "hero": "center", "steps": "dots",
                          "header": "split", "caps": "upper", "wave": "off", "game": "on"}},
    "Energy Gaming": {"description": "E-Sport-Look in Energy-Rot: Spieler-Seitenleiste mit Level & Missionen, "
                                     "schräge Kanten, Spielmodus an.",
                      "colors": "Energy Gaming",
                      "layout": {"skin": "esport", "width": "wide", "hero": "left", "steps": "dots",
                                 "header": "split", "caps": "upper", "wave": "off", "game": "on"}},
    "Jump & Run": {"description": "Plattform-Spiel: Himmel, Wolken, Ziegelboden, Münzen als Schritte, ?-Block, Spielmodus an.",
                   "colors": "Jump & Run",
                   "layout": {"skin": "jumprun", "width": "narrow", "hero": "center", "steps": "dots",
                              "header": "split", "caps": "normal", "wave": "off", "game": "on"}},
    "Candy Pop": {"description": "Bonbonbuntes Handyspiel: Seifenblasen, Wackelpudding-Knöpfe, runde Schrift, Spielmodus an.",
                  "colors": "Candy Pop",
                  "layout": {"skin": "candy", "width": "narrow", "hero": "center", "steps": "dots",
                             "header": "center", "caps": "normal", "wave": "on", "game": "on"}},
    "Black Friday": {"description": "Monochrom in Schwarz-Weiß: Laufband „BLACK FRIDAY“, riesige Schrift, Sale-Look.",
                     "colors": "Black Friday",
                     "layout": {"skin": "blackfriday", "width": "wide", "hero": "left", "steps": "dots",
                                "header": "split", "caps": "upper", "wave": "off", "game": "off"}},
    "Kompakt": {"description": "Wenig Kopfbereich, Punkte-Navigation – schnell beim Formular.", "colors": None,
                "layout": {"skin": "classic", "width": "narrow", "hero": "compact", "steps": "dots",
                           "header": "center", "caps": "normal", "wave": "off"}},
}

PRESETS["Arcade"] = {
    "page_bg": "#0b0a1f", "page_text": "#ffffff", "logo_accent": "#ffe600", "panel_bg": "#15133a",
    "field_bg": "#211e52", "line": "#4a46a8", "text": "#f4f4ff", "text_muted": "#aaa7e6",
    "accent": "#ff2bd6", "accent_soft": "#3d1450", "accent_2": "#00e5ff", "button_text": "#ffffff",
    "success": "#39ff14", "danger": "#ff5c5c",
}

PRESETS["Energy Gaming"] = {
    "page_bg": "#e2001a", "page_text": "#ffffff", "logo_accent": "#0d0d0d", "panel_bg": "#141416",
    "field_bg": "#1f1f23", "line": "#36363d", "text": "#f5f5f7", "text_muted": "#a3a3ad",
    "accent": "#e4002b", "accent_soft": "#3a0b12", "accent_2": "#ff4d5e", "button_text": "#ffffff",
    "success": "#2ee66b", "danger": "#ff6b6b",
}

PRESETS["Jump & Run"] = {
    "page_bg": "#5c94fc", "page_text": "#ffffff", "logo_accent": "#fbd000", "panel_bg": "#ffffff",
    "field_bg": "#fff6dc", "line": "#2b2b2b", "text": "#1d1d1d", "text_muted": "#5a5a5a",
    "accent": "#e52521", "accent_soft": "#ffe0de", "accent_2": "#43b047", "button_text": "#ffffff",
    "success": "#2e9e3a", "danger": "#e52521",
}
PRESETS["Candy Pop"] = {
    "page_bg": "#ff8fc7", "page_text": "#ffffff", "logo_accent": "#7b2ff7", "panel_bg": "#ffffff",
    "field_bg": "#fff3fa", "line": "#f5b5d8", "text": "#3b1d4a", "text_muted": "#8a6a99",
    "accent": "#ff3d8b", "accent_soft": "#ffe0ef", "accent_2": "#7b2ff7", "button_text": "#ffffff",
    "success": "#19c37d", "danger": "#ff3d3d",
}

PRESETS["Black Friday"] = {
    "page_bg": "#000000", "page_text": "#ffffff", "logo_accent": "#9a9a9a", "panel_bg": "#ffffff",
    "field_bg": "#f2f2f2", "line": "#111111", "text": "#000000", "text_muted": "#555555",
    "accent": "#000000", "accent_soft": "#e9e9e9", "accent_2": "#000000", "button_text": "#ffffff",
    "success": "#000000", "danger": "#000000",
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_FONT_NAME = re.compile(r"[A-Za-z0-9 ]{2,40}")


def get_theme(db: Session) -> dict[str, str]:
    stored = {s.key[6:]: s.value for s in db.query(Setting).filter(Setting.key.like("theme_%"))}
    theme = ({k: v[1] for k, v in COLORS.items()} | FONT_DEFAULTS | {k: v[1] for k, v in TEXTS.items()}
             | {"hero_size": str(HERO_SIZE_DEFAULT), "show_cta": "on", "show_firma": "on"} | LAYOUT_DEFAULTS)
    theme.update({k: v for k, v in stored.items() if k in theme})
    return theme


def validate(values: dict[str, str]) -> dict[str, str]:
    """Prüft Farben (#rrggbb) und Schriftnamen; wirft ValueError mit verständlicher Meldung."""
    clean = {}
    for key, (label, _, _) in COLORS.items():
        value = (values.get(key) or "").strip()
        if not _HEX.fullmatch(value):
            raise ValueError(f"{label}: bitte eine Farbe im Format #RRGGBB angeben")
        clean[key] = value.lower()
    for key in FONT_DEFAULTS:
        value = (values.get(key) or "").strip()
        if value != SYSTEM_FONT and not _FONT_NAME.fullmatch(value):
            raise ValueError("Schriftart: nur Buchstaben, Ziffern und Leerzeichen (Name wie bei Google Fonts)")
        clean[key] = value
    for key, (label, default, max_len) in TEXTS.items():
        value = " ".join(str(values.get(key) or "").split())  # keine Zeilenumbrüche/Mehrfach-Leerzeichen
        if len(value) > max_len:
            raise ValueError(f"{label}: höchstens {max_len} Zeichen")
        clean[key] = value or default
    try:
        size = int(str(values.get("hero_size") or HERO_SIZE_DEFAULT).strip().rstrip("%"))
    except ValueError as e:
        raise ValueError("Größe der Überschrift: bitte eine ganze Zahl in Prozent angeben") from e
    clean["hero_size"] = str(min(HERO_SIZE_MAX, max(HERO_SIZE_MIN, size)))
    # Felder „Firma / Marke“ und „Call-to-Action“ in Schritt „Text“ (Checkbox: fehlt = ausgeblendet)
    for key in ("show_firma", "show_cta"):
        clean[key] = "on" if values.get(key) == "on" else "off"
    clean.update(validate_layout(values))
    return clean


def validate_layout(values: dict[str, str]) -> dict[str, str]:
    """Unbekannte Werte fallen auf den Standard zurück (Formular lässt nur gültige zu)."""
    clean = {}
    for key, (_, choices, default) in LAYOUT.items():
        value = str(values.get(f"layout_{key}") or default)
        clean[f"layout_{key}"] = value if value in choices else default
    return clean


def variant_layout(name: str) -> dict[str, str]:
    layout = VARIANTS[name]["layout"]
    return {f"layout_{k}": layout.get(k, v[2]) for k, v in LAYOUT.items()}


def body_class(theme: dict[str, str]) -> str:
    return " ".join(f"lay-{k}-{theme.get(f'layout_{k}', v[2])}" for k, v in LAYOUT.items())


def save_theme(db: Session, values: dict[str, str]) -> None:
    for key, value in validate(values).items():
        db.merge(Setting(key=f"theme_{key}", value=value))
    db.commit()


def reset_theme(db: Session) -> None:
    db.query(Setting).filter(Setting.key.like("theme_%")).delete(synchronize_session=False)
    db.commit()


def version(theme: dict[str, str]) -> str:
    """Kurzer Hash für Cache-Busting (/theme.css?v=…)."""
    return hashlib.sha1(repr(sorted(theme.items())).encode()).hexdigest()[:10]


def families(theme: dict[str, str]) -> set[str]:
    skin = SKINS_WITH_FONT.get(theme.get("layout_skin", ""))
    return ({theme["font_body"], theme["font_heading"]} | ({skin} if skin else set())) - {SYSTEM_FONT}


def fonts_url(theme: dict[str, str]) -> str | None:
    """Lokale Schriften (/fonts.css) – keine Verbindung der Besucher zu Google."""
    return f"/fonts.css?v={version(theme)}" if families(theme) else None


def _stack(font: str) -> str:
    return "system-ui, -apple-system, 'Segoe UI', sans-serif" if font == SYSTEM_FONT else f"'{font}', system-ui, sans-serif"


def css(theme: dict[str, str]) -> str:
    t = theme
    return f"""/* Automatisch erzeugt aus Admin → Design */
:root, :root:not([data-theme="light"]), :root[data-theme="dark"] {{
  --bg: {t['page_bg']}; --page-text: {t['page_text']}; --logo-accent: {t['logo_accent']};
  --sans: {_stack(t['font_body'])}; --head: {_stack(t['font_heading'])};
  --page-accent: {t['accent']}; --page-panel: {t['panel_bg']};
}}
header.top {{ border-bottom-color: color-mix(in srgb, var(--page-text) 28%, transparent); }}
.wordmark, .hero h1 {{ color: var(--page-text); }}
.hero h1 {{ font-size: calc(clamp(1.9rem, 4.4vw, 2.9rem) * {int(t.get('hero_size', HERO_SIZE_DEFAULT)) / 100:g});
           overflow-wrap: break-word; }}
.wordmark span {{ color: var(--logo-accent); }}
.tag, .hero p {{ color: color-mix(in srgb, var(--page-text) 88%, transparent); }}
.wave i {{ background: var(--page-text); }}
footer {{ border-top-color: color-mix(in srgb, var(--page-text) 28%, transparent);
         color: color-mix(in srgb, var(--page-text) 85%, transparent); }}
.panel {{
  --bg-panel: {t['panel_bg']}; --bg-field: {t['field_bg']}; --line: {t['line']};
  --line-soft: color-mix(in srgb, {t['line']} 55%, {t['panel_bg']});
  --text: {t['text']}; --text-muted: {t['text_muted']};
  --accent: {t['accent']}; --accent-soft: {t['accent_soft']}; --accent-2: {t['accent_2']};
  --danger: {t['danger']}; --success: {t['success']}; --button-text: {t['button_text']};
}}
.panel .btn {{ color: var(--button-text); }}
.panel .btn.ghost {{ color: var(--text); }}
.price-table .discount td {{ color: var(--success); }}
"""
