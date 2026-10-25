import json
import re
from pathlib import Path

from app.models import CoverageArea, Package, Setting, SpotLength, Station, TimeSlot
from app.pricing import calculate_quote
from app.schemas import QuoteIn
from app.seed import ensure_coverage_areas, ensure_example_packages

MAP = Path(__file__).resolve().parent.parent / "app" / "static" / "austria-map.json"


def _login(client):
    t = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": t})


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def test_map_file_has_all_states():
    data = json.loads(MAP.read_text(encoding="utf-8"))
    assert {s["key"] for s in data["states"]} == {
        "burgenland", "kaernten", "niederoesterreich", "oberoesterreich", "salzburg", "steiermark", "tirol",
        "vorarlberg", "wien"}
    assert all(s["d"].startswith("M") for s in data["states"])
    wien = next(c for c in data["cities"] if c["name"] == "Wien")
    x, y = wien["xy"]
    assert x > 0.85 * data["viewBox"][2] and y < 0.4 * data["viewBox"][3]  # Wien liegt im Nordosten


def test_examples_created_once_and_linked(db):
    db.add(Station(name="Radio Energy Österreich", price_per_second_cent=850))
    db.commit()
    ensure_example_packages(db)
    ensure_coverage_areas(db)
    names = [a.name for a in db.query(CoverageArea).order_by(CoverageArea.sort_order)]
    assert names == ["DAB+ National", "UKW Wien", "UKW Salzburg", "UKW Innsbruck"]
    st = db.query(Station).one()
    ids = {a.name: a.id for a in db.query(CoverageArea)}
    assert st.coverage_ids == [ids["DAB+ National"], ids["UKW Wien"]]
    assert len(db.query(Package).filter_by(name="Kombi Radio & Streams").one().coverage_ids) == 4
    db.query(CoverageArea).delete()
    db.commit()
    ensure_coverage_areas(db)  # gelöschte Beispiele kommen nicht zurück
    assert db.query(CoverageArea).count() == 0 and db.get(Setting, "coverage_examples_created")


def test_admin_create_and_validate(client, db):
    _login(client)
    page = client.get("/admin/coverage/new").text
    assert 'id="coverageAdminMap"' in page and 'value="niederoesterreich"' in page
    token = _csrf(client, "/admin/coverage/new")
    base = {"csrf": token, "name": "UKW Graz", "technology": "ukw", "center_lat": "47,0707", "center_lon": "15,4395",
            "radius_km": "40", "reach_text": "Graz und Umgebung", "sort_order": "5", "active": "on"}
    r = client.post("/admin/coverage/new", data={**base, "states": ["steiermark", "gibtsnicht"]})
    assert "gespeichert" in r.text
    a = db.query(CoverageArea).filter_by(name="UKW Graz").one()
    assert a.states == ["steiermark"] and a.center_lat == 47.0707 and a.radius_km == 40
    for data, msg in [({"technology": "dab", "states": []}, "DAB+: bitte die Bundesländer"),
                      ({"center_lat": "", "center_lon": "", "states": []}, "UKW: bitte Bundesländer wählen"),
                      ({"center_lat": "52,5", "center_lon": "13,4"}, "nicht in Österreich"),
                      ({"center_lon": ""}, "Breiten- und Längengrad")]:
        r = client.post("/admin/coverage/new", data={**base, "name": "X", **data})
        assert msg in r.text, msg
    # am Sender ankreuzen
    token = _csrf(client, "/admin/stations/new")
    r = client.post("/admin/stations/new", data={"csrf": token, "name": "Energy Graz", "kind": "radio",
                    "price_per_second_cent": "5", "coverage_ids": [str(a.id)], "sort_order": "1", "active": "on"})
    assert "gespeichert" in r.text
    assert db.query(Station).filter_by(name="Energy Graz").one().coverage_ids == [a.id]
    assert "UKW Graz (UKW)" in client.get("/admin/stations").text


def test_catalog_quote_and_pdf_show_coverage(client, db):
    area = CoverageArea(name="UKW Wien", technology="ukw", states=["wien"], center_lat=48.2, center_lon=16.37,
                        radius_km=45, reach_text="Wien und Umgebung")
    db.add(area)
    db.flush()
    db.add_all([Station(name="Radio A", price_per_second_cent=1000, coverage_ids=[area.id]),
                TimeSlot(name="Tag"), SpotLength(seconds=20)])
    db.commit()
    cat = client.get("/api/catalog").json()
    assert cat["coverage_areas"][0]["name"] == "UKW Wien" and cat["stations"][0]["coverage_ids"] == [area.id]
    q = calculate_quote(db, QuoteIn(country="AT", items=[{"station_id": 1, "time_slot_id": 1, "spot_length_id": 1,
                                                           "spots": 2}]))
    assert q.lines[0].coverage == "UKW Wien"
    assert client.get("/static/austria-map.json").status_code == 200
    assert client.get("/static/coverage-map.js").status_code == 200


def test_station_and_area_colors(client, db):
    from app.seed import ensure_station_colors
    db.add_all([Station(name="Radio Nostalgie", price_per_second_cent=700),
                Station(name="Radio Energy Österreich", price_per_second_cent=850, map_color="#123456")])
    db.query(Setting).filter_by(key="station_colors_set").delete()  # der Testserver hat beim Start schon geprüft
    db.commit()
    ensure_station_colors(db)
    assert db.query(Station).filter_by(name="Radio Nostalgie").one().map_color == "#0057b8"
    assert db.query(Station).filter_by(name="Radio Energy Österreich").one().map_color == "#123456"  # bleibt
    st = db.query(Station).filter_by(name="Radio Nostalgie").one()
    st.map_color = ""
    db.commit()
    ensure_station_colors(db)  # nur einmal – eine bewusst geleerte Farbe bleibt leer
    assert db.get(Station, st.id).map_color == ""

    _login(client)
    token = _csrf(client, "/admin/coverage/new")
    base = {"csrf": token, "name": "Nostalgie UKW Wien", "technology": "ukw", "states": ["wien"], "center_lat": "",
            "center_lon": "", "radius_km": "0", "reach_text": "", "sort_order": "1", "active": "on"}
    assert "gespeichert" in client.post("/admin/coverage/new", data={**base, "color": "#0057B8"}).text
    assert db.query(CoverageArea).filter_by(name="Nostalgie UKW Wien").one().color == "#0057b8"
    assert "#RRGGBB" in client.post("/admin/coverage/new", data={**base, "name": "X", "color": "blau"}).text
    page = client.get(f"/admin/stations/{st.id}").text
    assert 'name="map_color"' in page and "Nostalgie-Blau" in page
    r = client.post(f"/admin/stations/{st.id}", data={"csrf": token, "name": "Radio Nostalgie", "kind": "radio",
                    "price_per_second_cent": "7", "map_color": "#0057b8", "sort_order": "2", "active": "on"})
    assert "gespeichert" in r.text
    cat = client.get("/api/catalog").json()
    assert next(s for s in cat["stations"] if s["name"] == "Radio Nostalgie")["map_color"] == "#0057b8"
    assert next(a for a in cat["coverage_areas"] if a["name"] == "Nostalgie UKW Wien")["color"] == "#0057b8"
