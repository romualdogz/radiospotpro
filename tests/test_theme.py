import re

from app import theme


def _login(client):
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})


def _csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def _form(design, **changes):
    return {**design, **changes}


def test_default_theme_matches_template(client, db):
    css = client.get("/theme.css").text
    assert "--bg: #e2001a" in css and "--accent: #e4002b" in css
    assert "'IBM Plex Sans'" in css and "'Space Grotesk'" in css
    page = client.get("/").text
    assert "fonts.googleapis.com/css2?family=IBM+Plex+Sans" in page and "/theme.css?v=" in page


def test_admin_saves_colors_and_fonts(client, db):
    _login(client)
    design = theme.get_theme(db)
    token = _csrf(client, "/admin/design")
    r = client.post("/admin/design", data=_form(design, csrf=token, action="save", page_bg="#003366",
                    accent="#FF8800", font_heading="Montserrat", font_body="custom", font_body_custom="Lexend"),
                    follow_redirects=False)
    assert r.status_code == 303
    css = client.get("/theme.css").text
    assert "--bg: #003366" in css and "--accent: #ff8800" in css
    assert "--head: 'Montserrat'" in css and "--sans: 'Lexend'" in css
    page = client.get("/").text
    assert "family=Lexend" in page and "family=Montserrat" in page


def test_system_font_loads_no_google_fonts(client, db):
    _login(client)
    token = _csrf(client, "/admin/design")
    client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save",
                                            font_heading="system", font_body="system"))
    assert "fonts.googleapis.com" not in client.get("/").text
    assert "--sans: system-ui" in client.get("/theme.css").text


def test_invalid_values_rejected(client, db):
    _login(client)
    token = _csrf(client, "/admin/design")
    r = client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save", accent="rot"))
    assert "Format #RRGGBB" in r.text
    r = client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save",
                                                font_body="custom", font_body_custom="x'); body{"))
    assert "Schriftart" in r.text
    assert "--accent: #e4002b" in client.get("/theme.css").text  # unverändert


def test_preset_and_reset(client, db):
    _login(client)
    token = _csrf(client, "/admin/design")
    client.post("/admin/design", data={"csrf": token, "action": "preset:Dunkel"})
    assert "--bg: #111111" in client.get("/theme.css").text
    client.post("/admin/design", data={"csrf": token, "action": "reset"})
    assert "--bg: #e2001a" in client.get("/theme.css").text


def test_pdf_uses_accent(db):
    from types import SimpleNamespace
    from datetime import datetime
    from app.pdf import build_request_pdf
    req = SimpleNamespace(id=1, created_at=datetime(2026, 10, 24), customer_name="E", company="", street="", zip_code="",
                          city="", email="e@example.com", phone="", message="", brief={}, configuration={}, quote={})
    assert build_request_pdf(req, "x", "#003366").startswith(b"%PDF")
