"""Erzeugt app/static/austria-map.json (Bundesländer als SVG-Pfade) aus Natural-Earth-Daten.

Natural Earth ist gemeinfrei (public domain) – keine Quellenangabe nötig.
Nur nötig, wenn die Karte neu erzeugt werden soll:

  curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
  python scripts/build_austria_map.py ne_10m_admin_1_states_provinces.geojson
"""
import json
import math
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "austria-map.json"
WIDTH = 1000.0
PAD = 12.0
KEYS = {"AT-1": "burgenland", "AT-2": "kaernten", "AT-3": "niederoesterreich", "AT-4": "oberoesterreich",
        "AT-5": "salzburg", "AT-6": "steiermark", "AT-7": "tirol", "AT-8": "vorarlberg", "AT-9": "wien"}
# Landeshauptstädte und größere Städte für Beschriftung und als Auswahl für Sender-Standorte
CITIES = [
    ("Wien", 48.2082, 16.3738), ("Graz", 47.0707, 15.4395), ("Linz", 48.3069, 14.2858),
    ("Salzburg", 47.8095, 13.0550), ("Innsbruck", 47.2692, 11.4041), ("Klagenfurt", 46.6247, 14.3053),
    ("Villach", 46.6111, 13.8558), ("Wels", 48.1575, 14.0289), ("St. Pölten", 48.2047, 15.6256),
    ("Dornbirn", 47.4125, 9.7417), ("Bregenz", 47.5031, 9.7471), ("Eisenstadt", 47.8456, 16.5233),
    ("Leoben", 47.3765, 15.0910), ("Krems", 48.4092, 15.6142), ("Lienz", 46.8289, 12.7690),
]


def rings(geometry):
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [ring for poly in polys for ring in poly]


def simplify(points, tol):
    """Douglas-Peucker – entfernt Punkte, die weniger als tol (px) von der Linie abweichen."""
    if len(points) < 4:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-9
    dists = [abs(dy * (x - x1) - dx * (y - y1)) / norm for x, y in points[1:-1]]
    i = max(range(len(dists)), key=dists.__getitem__)
    if dists[i] <= tol:
        return [points[0], points[-1]]
    return simplify(points[: i + 2], tol)[:-1] + simplify(points[i + 1:], tol)


def simplify_ring(points, tol):
    """Geschlossener Ring: am weitest entfernten Punkt teilen, sonst fallen Start = Ende zusammen."""
    if points[0] == points[-1]:
        points = points[:-1]
    x0, y0 = points[0]
    far = max(range(len(points)), key=lambda i: (points[i][0] - x0) ** 2 + (points[i][1] - y0) ** 2)
    first = simplify(points[: far + 1], tol)
    second = simplify(points[far:] + [points[0]], tol)
    return first[:-1] + second[:-1]


def main(src: str) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    states = [f for f in data["features"] if f["properties"].get("adm0_a3") == "AUT"]
    all_pts = [pt for f in states for ring in rings(f["geometry"]) for pt in ring]
    lon_min = min(p[0] for p in all_pts); lon_max = max(p[0] for p in all_pts)
    lat_min = min(p[1] for p in all_pts); lat_max = max(p[1] for p in all_pts)
    kx = math.cos(math.radians((lat_min + lat_max) / 2))  # einfache, für Österreich ausreichende Projektion
    scale = (WIDTH - 2 * PAD) / ((lon_max - lon_min) * kx)
    height = (lat_max - lat_min) * scale + 2 * PAD

    def project(lon, lat):
        return (PAD + (lon - lon_min) * kx * scale, PAD + (lat_max - lat) * scale)

    out_states = []
    for f in sorted(states, key=lambda f: f["properties"]["iso_3166_2"]):
        p = f["properties"]
        parts, sx, sy, n = [], 0.0, 0.0, 0
        for ring in rings(f["geometry"]):
            pts = simplify_ring([project(lon, lat) for lon, lat in ring], 0.35)
            if len(pts) < 3:
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
            sx += sum(x for x, _ in pts); sy += sum(y for _, y in pts); n += len(pts)
        out_states.append({"key": KEYS[p["iso_3166_2"]], "code": p["iso_3166_2"], "name": p["name"],
                           "d": "".join(parts), "label": [round(sx / n, 1), round(sy / n, 1)]})

    result = {
        "source": "Natural Earth (public domain), 1:10m admin-1",
        "viewBox": [0, 0, WIDTH, round(height, 1)],
        "projection": {"lon_min": lon_min, "lat_max": lat_max, "kx": kx, "scale": scale, "pad": PAD},
        "states": out_states,
        "cities": [{"name": n, "lat": lat, "lon": lon, "xy": [round(c, 1) for c in project(lon, lat)]}
                   for n, lat, lon in CITIES],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT} – {OUT.stat().st_size / 1024:.1f} KB, {len(out_states)} Bundesländer")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ne_10m_admin_1_states_provinces.geojson")
