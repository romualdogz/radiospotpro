"""Logo des Konfigurators – im Admin unter „Design“ hochladbar.

Das Logo ersetzt den Schriftzug „onaircraft“ im Kopf von Konfigurator, AGB-/Datenschutz-Seite
und (bei PNG/JPG/WebP) im PDF. Dateien liegen unter media/logos.

Wurde im Admin noch nie ein Logo gespeichert, wird automatisch ein Bild verwendet, das direkt in
media/logos abgelegt wurde (bei mehreren das alphabetisch erste).
"""
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
import uuid
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from .config import settings
from .models import Setting

LOGO_DIR = settings.media_dir / "logos"
MAX_BYTES = 2 * 1024 * 1024
RASTER = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
EXTENSIONS = [*RASTER, ".svg"]
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".svg": "image/svg+xml"}
HEIGHT_DEFAULT, HEIGHT_MIN, HEIGHT_MAX = 40, 20, 120
HEIGHT_DEFAULT_TALL = 72  # hohe/quadratische Logos brauchen mehr Höhe, damit sie lesbar bleiben


def logo_path(name: str) -> Path | None:
    """Datei direkt in media/logos mit erlaubter Endung – sonst None (kein Pfad außerhalb des Ordners)."""
    if not name or Path(name).name != name or Path(name).suffix.lower() not in EXTENSIONS:
        return None
    path = LOGO_DIR / name
    return path if path.is_file() else None


def _aspect(path: Path) -> float | None:
    """Breite/Höhe des Logos (SVG über viewBox bzw. width/height)."""
    try:
        if path.suffix.lower() == ".svg":
            root = ElementTree.parse(path).getroot()
            box = (root.get("viewBox") or "").replace(",", " ").split()
            w, h = (float(box[2]), float(box[3])) if len(box) == 4 else (
                float(str(root.get("width")).rstrip("px")), float(str(root.get("height")).rstrip("px")))
        else:
            with Image.open(path) as img:
                w, h = img.size
        return w / h if h else None
    except (ValueError, TypeError, OSError, ElementTree.ParseError):
        return None


def get_logo(db: Session) -> dict | None:
    """{"file", "url", "height", "path", …} oder None, wenn kein Logo hinterlegt ist."""
    stored = {s.key: s.value for s in db.query(Setting).filter(
        Setting.key.in_(["logo_file", "logo_height", "logo_in_pdf"]))}
    if "logo_file" in stored:
        path = logo_path(stored["logo_file"])
    else:  # noch nie im Admin gesetzt → im Ordner abgelegtes Bild verwenden
        files = sorted(p.name for p in LOGO_DIR.glob("*") if p.is_file()) if LOGO_DIR.is_dir() else []
        path = next((p for p in map(logo_path, files) if p), None)
    if path is None:
        return None
    name = path.name
    if "logo_height" in stored:
        height = int(stored["logo_height"])
    else:
        aspect = _aspect(path)
        height = HEIGHT_DEFAULT_TALL if aspect is not None and aspect < 1.6 else HEIGHT_DEFAULT
    return {"file": name, "url": f"/media/logo/{quote(name)}", "height": height, "path": path,
            "in_pdf": stored.get("logo_in_pdf", "1") == "1", "pdf_capable": path.suffix.lower() in RASTER}


def _check(content: bytes, ext: str) -> None:
    if len(content) > MAX_BYTES:
        raise ValueError("Das Logo ist größer als 2 MB.")
    if ext == ".svg":
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as e:
            raise ValueError("Die SVG-Datei ist ungültig.") from e
        if not root.tag.endswith("svg"):
            raise ValueError("Die Datei ist keine SVG-Grafik.")
        return
    try:
        with Image.open(BytesIO(content)) as img:
            if img.format != RASTER[ext]:
                raise ValueError("Dateiendung und Bildformat passen nicht zusammen.")
            img.verify()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Die Datei konnte nicht als Bild gelesen werden.") from e


def save_logo(db: Session, filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in EXTENSIONS:
        raise ValueError("Bitte ein Logo als PNG, JPG, WebP oder SVG hochladen.")
    _check(content, ext)
    old = get_logo(db)
    name = f"logo-{uuid.uuid4().hex[:12]}{ext}"
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    (LOGO_DIR / name).write_bytes(content)
    db.merge(Setting(key="logo_file", value=name))
    db.commit()
    _delete_uploaded(old)
    return name


def set_options(db: Session, height: int, in_pdf: bool) -> None:
    db.merge(Setting(key="logo_height", value=str(min(HEIGHT_MAX, max(HEIGHT_MIN, height)))))
    db.merge(Setting(key="logo_in_pdf", value="1" if in_pdf else "0"))
    db.commit()


def remove_logo(db: Session) -> None:
    old = get_logo(db)
    # leerer Eintrag statt Löschen: sonst würde ein anderes Bild aus dem Ordner automatisch nachrücken
    db.merge(Setting(key="logo_file", value=""))
    db.commit()
    _delete_uploaded(old)


def _delete_uploaded(logo: dict | None) -> None:
    """Nur im Admin hochgeladene Dateien löschen – von Hand in media/logos abgelegte bleiben erhalten."""
    if logo and logo["file"].startswith("logo-"):
        logo["path"].unlink(missing_ok=True)


def pdf_image_path(logo: dict | None) -> Path | None:
    """reportlab kann Rasterbilder einbinden, aber kein SVG – dann bleibt der Schriftzug."""
    return logo["path"] if logo and logo["in_pdf"] and logo["pdf_capable"] else None
