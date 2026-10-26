"""Lädt alle Schriften aus theme.FONTS nach app/static/fonts/ (werden mit dem Projekt mitgeliefert).

Nur nötig, wenn die Auswahl in app/theme.py erweitert wird:

  python scripts/fetch_fonts.py            # fehlende Schriften laden
  python scripts/fetch_fonts.py --all      # alle neu laden
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fonts, theme  # noqa: E402


def main(refresh: bool) -> None:
    for family, weights in [(f, fonts.WEIGHTS) for f in theme.FONTS] + list(theme.SKIN_FONTS.items()):
        folder = fonts.BUNDLED_DIR / fonts.slug(family)
        if (folder / "font.css").is_file() and not refresh:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        fonts.download(family, folder, f"/static/fonts/{fonts.slug(family)}", weights)
        size = sum(f.stat().st_size for f in folder.iterdir()) / 1024
        print(f"{family:20} {len(list(folder.glob('*.woff2')))} Dateien, {size:.0f} KB"
              + ("" if (folder / "OFL.txt").exists() else "  (ohne Lizenzdatei!)"))


if __name__ == "__main__":
    main("--all" in sys.argv)
