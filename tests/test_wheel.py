import re

import pytest

from app import wheel
from app.models import AdminUser, Package
from app.pricing import calculate_quote
from app.schemas import QuoteIn
from app.security import hash_password

SEGMENTS = [{"label": "10 %", "percent": 10, "weight": 1}, {"label": "Niete", "percent": 0, "weight": 0}]


@pytest.fixture(autouse=True)
def _fresh_memory():
    wheel.reset_memory()
    yield
    wheel.reset_memory()


@pytest.fixture()
def pkg(db):
    p = Package(name="Basic", price_cent=100000, spots=40)
    db.add(p)
    db.commit()
    return p


def _quote(db, pkg, token=None, promo=None):
    return calculate_quote(db, QuoteIn(country="AT", package_id=pkg.id, wheel_token=token, promo_code=promo))


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def test_disabled_by_default(client, db):
    assert client.get("/api/catalog").json()["wheel"] is None
    assert client.post("/api/wheel/spin").status_code == 404


def test_spin_gives_signed_discount_on_package(client, db, pkg):
    wheel.save_config(db, True, False, 72, SEGMENTS)
    assert [s["label"] for s in client.get("/api/catalog").json()["wheel"]["segments"]] == ["10 %", "Niete"]
    r = client.post("/api/wheel/spin").json()
    assert r["index"] == 0 and r["percent"] == 10 and r["token"] and not r["repeat"]
    q = _quote(db, pkg, r["token"])
    assert q.wheel_status == "applied" and q.discounts[0].name == "Glücksrad-Rabatt 10 %"
    assert q.net_cent == 90000  # gilt auch für Komplettpakete (Gesamtbetrag)


def test_same_result_when_spinning_again(client, db):
    wheel.save_config(db, True, False, 72, [{"label": "A", "percent": 5, "weight": 1},
                                             {"label": "B", "percent": 0, "weight": 1}])
    first = client.post("/api/wheel/spin").json()
    for _ in range(5):
        again = client.post("/api/wheel/spin").json()
        assert again["index"] == first["index"] and again["repeat"] and again["token"] == first["token"]


def test_forged_or_expired_token_ignored(client, db, pkg):
    wheel.save_config(db, True, False, 72, SEGMENTS)
    token = client.post("/api/wheel/spin").json()["token"]
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    q = _quote(db, pkg, forged)
    assert q.wheel_status == "invalid" and q.net_cent == 100000
    wheel.save_config(db, False, False, 72, SEGMENTS)  # Rad abgeschaltet → Gewinne verfallen
    assert _quote(db, pkg, token).wheel_status == "invalid"
    wheel.save_config(db, True, False, 72, [{"label": "3 %", "percent": 3, "weight": 1},
                                             {"label": "Niete", "percent": 0, "weight": 1}])
    assert _quote(db, pkg, token).wheel_status == "invalid"  # 10 % gibt es nicht mehr auf dem Rad


def test_not_stackable_better_discount_wins(client, db, pkg):
    from app.models import Discount, DiscountKind, DiscountScope
    db.add(Discount(name="Aktion", kind=DiscountKind.percent, value=2000, applies_to=DiscountScope.total))
    db.commit()
    wheel.save_config(db, True, False, 72, SEGMENTS)
    q = _quote(db, pkg, client.post("/api/wheel/spin").json()["token"])
    assert q.wheel_status == "superseded" and [d.name for d in q.discounts] == ["Aktion"]
    wheel.save_config(db, True, True, 72, SEGMENTS)  # kombinierbar → beide
    q = _quote(db, pkg, client.post("/api/wheel/spin").json()["token"])
    assert q.wheel_status == "applied" and len(q.discounts) == 2


def test_validation():
    with pytest.raises(ValueError, match="2 bis 12"):
        wheel.validate_segments([{"label": "nur eins", "percent": 5, "weight": 1}])
    with pytest.raises(ValueError, match="zwischen 0 und 50"):
        wheel.validate_segments([{"label": "A", "percent": 80, "weight": 1}, {"label": "B", "percent": 0, "weight": 1}])
    with pytest.raises(ValueError, match="Gewichtung über 0"):
        wheel.validate_segments([{"label": "A", "percent": 5, "weight": 0}, {"label": "B", "percent": 0, "weight": 0}])


def test_admin_page_for_sales(client, db):
    db.add(AdminUser(username="verkauf", password_hash=hash_password("verkauf-passwort"), role="sales"))
    db.commit()
    token = _csrf(client, "/admin/login")
    client.post("/admin/login", data={"username": "verkauf", "password": "verkauf-passwort", "csrf": token})
    page = client.get("/admin/wheel").text
    assert "Rabatt-Glücksrad" in page and 'href="/admin/wheel"' in page
    token = _csrf(client, "/admin/wheel")
    r = client.post("/admin/wheel", data={"csrf": token, "enabled": "on", "valid_hours": "48",
                                          "label": ["5 %", "Niete", ""], "percent": ["5", "0", ""],
                                          "weight": ["1", "3", ""]}, follow_redirects=False)
    assert r.status_code == 303
    cfg = wheel.get_config(db)
    assert cfg.enabled and cfg.valid_hours == 48 and len(cfg.segments) == 2 and cfg.win_chance == 0.25
    r = client.post("/admin/wheel", data={"csrf": token, "label": ["A"], "percent": ["90"], "weight": ["1"]})
    assert "2 bis 12" in r.text or "zwischen 0 und 50" in r.text


def test_popup_mode(client, db):
    wheel.save_config(db, True, False, 72, SEGMENTS, mode="popup", popup_step="3")
    w = client.get("/api/catalog").json()["wheel"]
    assert w["mode"] == "popup" and w["popup_step"] == 3
    wheel.save_config(db, True, False, 72, SEGMENTS, mode="quatsch", popup_step="9")
    w = client.get("/api/catalog").json()["wheel"]
    assert w["mode"] == "inline" and w["popup_step"] == 4
