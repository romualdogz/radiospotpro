import re

from app.models import AdminUser, Country
from app.security import hash_password


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def _login(client, username, password):
    token = _csrf(client, "/admin/login")
    r = client.post("/admin/login", data={"username": username, "password": password, "csrf": token},
                    follow_redirects=False)
    assert r.status_code == 303


def _sales_user(client, db):
    _login(client, "admin", "test-password")
    token = _csrf(client, "/admin/users")
    r = client.post("/admin/users/new", data={"csrf": token, "username": "verkauf",
                                              "password": "verkauf-passwort", "role": "sales"})
    assert "angelegt" in r.text
    assert db.query(AdminUser).filter_by(username="verkauf").one().role == "sales"
    client.post("/admin/logout", data={"csrf": token})
    _login(client, "verkauf", "verkauf-passwort")


def test_sales_can_edit_countries_and_prices(client, db):
    _sales_user(client, db)
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/prices"
    page = client.get("/admin/prices").text
    assert "Länder" in page and "Design" not in page and "Anfragen" not in page
    token = _csrf(client, "/admin/prices")
    client.post("/admin/prices", data={"csrf": token, "studio_price": "399", "ad_tax_rate": "5", "min_order": "0",
                                       "currency": "EUR"})
    assert "399,00" in client.get("/admin/prices").text
    at = db.query(Country).filter_by(code="AT").one()
    r = client.post(f"/admin/countries/{at.id}", data={"csrf": token, "name": "Österreich", "code": "AT",
                                                       "vat_rate_bp": "10", "reverse_charge": "", "sort_order": "1",
                                                       "active": "on"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Country, at.id).vat_rate_bp == 1000
    for path in ["/admin/stations", "/admin/time-slots", "/admin/addons", "/admin/discounts", "/admin/account"]:
        assert client.get(path).status_code == 200, path


def test_sales_is_blocked_elsewhere(client, db):
    _sales_user(client, db)
    for path in ["/admin/requests", "/admin/design", "/admin/legal", "/admin/settings", "/admin/users",
                 "/admin/voices", "/admin/music-styles", "/admin/voices/new"]:
        r = client.get(path)
        assert r.status_code == 403 and "Kein Zugriff" in r.text, path
    token = _csrf(client, "/admin/account")
    assert client.post("/admin/voices/new", data={"csrf": token, "name": "X"}).status_code == 403
    assert client.post("/admin/users/new", data={"csrf": token, "username": "hacker", "password": "x" * 12,
                                                 "role": "admin"}).status_code == 403
    assert client.get("/api/admin/countries", auth=("verkauf", "verkauf-passwort")).status_code == 403


def test_sales_changes_own_password(client, db):
    _sales_user(client, db)
    token = _csrf(client, "/admin/account")
    r = client.post("/admin/password", data={"csrf": token, "current": "verkauf-passwort", "new": "neues-passwort-1"})
    assert "Passwort geändert" in r.text


def test_last_admin_and_self_are_protected(client, db):
    _login(client, "admin", "test-password")
    me = db.query(AdminUser).filter_by(username="admin").one()
    token = _csrf(client, "/admin/users")
    assert "nicht selbst löschen" in client.post(f"/admin/users/{me.id}/delete", data={"csrf": token}).text
    r = client.post(f"/admin/users/{me.id}", data={"csrf": token, "role": "sales", "password": ""})
    assert "mindestens ein Administrator" in r.text
    other = AdminUser(username="chef", password_hash=hash_password("x" * 12), role="admin")
    db.add(other)
    db.commit()
    r = client.post(f"/admin/users/{other.id}", data={"csrf": token, "role": "sales", "password": "neu-passwort-99"})
    assert "neues Passwort gesetzt" in r.text
    assert "gelöscht" in client.post(f"/admin/users/{other.id}/delete", data={"csrf": token}).text
    assert "gibt es schon" in client.post("/admin/users/new", data={
        "csrf": token, "username": "admin", "password": "x" * 12, "role": "sales"}).text


def test_role_column_added_to_old_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app import database

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username VARCHAR(80), "
                          "password_hash VARCHAR(255), created_at DATETIME)"))
        conn.execute(text("INSERT INTO admin_users (username, password_hash) VALUES ('alt', 'x')"))
    old_engine = database.engine
    database.engine = engine
    try:
        database.upgrade_schema()
    finally:
        database.engine = old_engine
    assert "role" in {c["name"] for c in inspect(engine).get_columns("admin_users")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT role FROM admin_users")).scalar() == "admin"
