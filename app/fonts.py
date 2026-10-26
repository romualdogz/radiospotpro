"""Schriften lokal ausliefern – Besucher laden nichts von Google (DSGVO).

Die Schriften aus theme.FONTS liegen fertig unter app/static/fonts/<slug>/ (mitgeliefert, erzeugt mit
scripts/fetch_fonts.py). Eine „andere Google-Font“ aus dem Admin wird beim Speichern einmalig vom
Server heruntergeladen und unter media/fonts/<slug>/ abgelegt. Ausgeliefert wird alles über /fonts.css.
Je Schrift: Schnitte 400–700, Zeichensätze latin und latin-ext (Deutsch, Tschechisch, Ungarisch …).
"""
import re
import urllib.request
from pathlib import Path

from .config import BASE_DIR, settings

BUNDLED_DIR = BASE_DIR / "static" / "fonts"
CUSTOM_DIR = settings.media_dir / "fonts"
SUBSETS = ("latin", "latin-ext")
WEIGHTS = "400;500;600;700"
# Google liefert woff2 nur an moderne Browser aus – daher eine aktuelle Browser-Kennung
_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BLOCK = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})")
_URL = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)")
MAX_FILE_BYTES = 2 * 1024 * 1024


def slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]", "", family.lower())


def _paths(family: str) -> list[tuple[Path, str]]:
    """Mögliche Ablageorte (Ordner, URL-Präfix) – mitgelieferte Schriften zuerst."""
    s = slug(family)
    return [(BUNDLED_DIR / s, f"/static/fonts/{s}"), (CUSTOM_DIR / s, f"/media/fonts/{s}")]


def is_local(family: str) -> bool:
    return any((folder / "font.css").is_file() for folder, _ in _paths(family))


def css_for(families) -> str:
    parts = []
    for family in sorted(set(families)):
        for folder, _ in _paths(family):
            css_file = folder / "font.css"
            if css_file.is_file():
                parts.append(css_file.read_text(encoding="utf-8"))
                break
    return "\n".join(parts)


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Schriftdatei ist zu groß")
    return data


def download(family: str, folder: Path | None = None, url_prefix: str | None = None, weights: str = WEIGHTS) -> Path:
    """Lädt die Schrift einmalig (vom Server aus) und legt font.css + woff2-Dateien ab.

    Ohne Angabe landet sie in media/fonts/. Wirft ValueError mit verständlicher Meldung.
    """
    s = slug(family)
    folder = folder or CUSTOM_DIR / s
    url_prefix = url_prefix or f"/media/fonts/{s}"
    api = (f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@{weights}"
           f"&display=swap")
    try:
        css = _get(api, 512 * 1024).decode("utf-8")
    except Exception as e:  # noqa: BLE001 – HTTP-Fehler, keine Verbindung …
        if getattr(e, "code", None) == 400:
            raise ValueError(f"„{family}“ gibt es bei Google Fonts nicht (Schreibweise prüfen) "
                             f"oder die Schrift hat nicht alle Schnitte 400–700.") from e
        raise ValueError(f"Schrift „{family}“ konnte nicht heruntergeladen werden "
                         f"(keine Internetverbindung?).") from e
    blocks = [block for subset, block in _BLOCK.findall(css) if subset in SUBSETS]
    if not blocks:
        raise ValueError(f"Für „{family}“ gibt es keine lateinischen Zeichen.")
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def local(match: re.Match) -> str:
        url = match.group(1)
        if url not in files:
            name = f"{s}-{len(files) + 1}.woff2"
            (folder / name).write_bytes(_get(url, MAX_FILE_BYTES))
            files[url] = name
        return f"url({url_prefix}/{files[url]})"

    out = [f"/* {family} – lokal ausgeliefert, Lizenz siehe Ordner {url_prefix} */"]
    for block in blocks:
        out.append(_URL.sub(local, block))
    (folder / "font.css").write_text("\n".join(out) + "\n", encoding="utf-8")
    try:  # Lizenz (SIL Open Font License) beilegen – fast alle Google Fonts stehen unter OFL
        (folder / "OFL.txt").write_bytes(
            _get(f"https://raw.githubusercontent.com/google/fonts/main/ofl/{s}/OFL.txt", 256 * 1024))
    except Exception:  # noqa: BLE001 – Lizenzdatei ist nice-to-have
        pass
    return folder


def ensure_local(family: str) -> None:
    """Für den Admin: Schrift beim Speichern lokal verfügbar machen."""
    if not is_local(family):
        download(family)
