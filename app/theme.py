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

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_FONT_NAME = re.compile(r"[A-Za-z0-9 ]{2,40}")


def get_theme(db: Session) -> dict[str, str]:
    stored = {s.key[6:]: s.value for s in db.query(Setting).filter(Setting.key.like("theme_%"))}
    theme = ({k: v[1] for k, v in COLORS.items()} | FONT_DEFAULTS | {k: v[1] for k, v in TEXTS.items()}
             | {"hero_size": str(HERO_SIZE_DEFAULT)})
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
    return clean


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
    return {theme["font_body"], theme["font_heading"]} - {SYSTEM_FONT}


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
