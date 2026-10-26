import re

from app import fonts, theme


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
    assert "/fonts.css?v=" in page and "/theme.css?v=" in page
    assert "googleapis" not in page and "gstatic" not in page  # DSGVO: nichts von Google laden
    fcss = client.get("/fonts.css").text
    assert "font-family: 'IBM Plex Sans'" in fcss and "font-family: 'Space Grotesk'" in fcss
    assert "gstatic" not in fcss
    for url in set(re.findall(r"url\((/static/fonts/[^)]+)\)", fcss)):
        r = client.get(url)
        assert r.status_code == 200 and r.content[:4] == b"wOF2"


def test_all_bundled_fonts_present():
    for family in theme.FONTS:
        folder = fonts.BUNDLED_DIR / fonts.slug(family)
        assert (folder / "font.css").is_file() and (folder / "OFL.txt").is_file(), family
        assert "gstatic" not in (folder / "font.css").read_text()


def test_admin_saves_colors_and_fonts(client, db, monkeypatch):
    loaded = []

    def fake_download(family):  # kein Internet im Test: Download der eigenen Schrift simulieren
        loaded.append(family)
        folder = fonts.CUSTOM_DIR / fonts.slug(family)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "font.css").write_text(f"@font-face {{ font-family: '{family}'; "
                                         f"src: url(/media/fonts/{fonts.slug(family)}/x.woff2); }}")
        (folder / "x.woff2").write_bytes(b"wOF2test")
    monkeypatch.setattr(fonts, "download", fake_download)
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
    assert "googleapis" not in page and loaded == ["Lexend"]  # Montserrat ist mitgeliefert
    fcss = client.get("/fonts.css").text
    assert "'Lexend'" in fcss and "'Montserrat'" in fcss and "IBM Plex" not in fcss
    assert client.get("/media/fonts/lexend/x.woff2").content == b"wOF2test"


def test_custom_font_download_error_shown(client, db, monkeypatch):
    def fail(family):
        raise ValueError(f"„{family}“ gibt es bei Google Fonts nicht (Schreibweise prüfen)")
    monkeypatch.setattr(fonts, "download", fail)
    _login(client)
    token = _csrf(client, "/admin/design")
    r = client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save",
                                                font_body="custom", font_body_custom="Gibtsnicht Sans"))
    assert "gibt es bei Google Fonts nicht" in r.text
    assert "--sans: 'IBM Plex Sans'" in client.get("/theme.css").text  # unverändert


def test_system_font_loads_no_google_fonts(client, db):
    _login(client)
    token = _csrf(client, "/admin/design")
    client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save",
                                            font_heading="system", font_body="system"))
    assert "/fonts.css" not in client.get("/").text
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


def test_hero_texts_and_size(client, db):
    import re
    from app import fonts, theme
    t = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": t})
    page = client.get("/admin/design").text
    assert 'name="hero_title"' in page and 'name="hero_size"' in page
    assert "Ihr Radiospot, angehört, bevor er läuft." in client.get("/").text

    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    form = {**theme.get_theme(db), "csrf": token, "action": "save",
            "hero_title": "AD-BOOST: Dein Radiospot\nin Minuten", "tagline": "Radio Energy Österreich", "hero_size": "130"}
    r = client.post("/admin/design", data=form)
    assert "Design gespeichert" in r.text
    home = client.get("/").text
    assert "<h1>AD-BOOST: Dein Radiospot in Minuten</h1>" in home and "Radio Energy Österreich" in home
    assert "Radio Energy Österreich" in client.get("/agb").text
    assert "* 1.3)" in client.get("/theme.css").text

    r = client.post("/admin/design", data={**form, "hero_title": "x" * 121})
    assert "höchstens 120 Zeichen" in r.text
    client.post("/admin/design", data={**form, "hero_title": "", "hero_size": "999"})
    d = theme.get_theme(db)
    assert d["hero_title"] == "Ihr Radiospot, angehört, bevor er läuft." and d["hero_size"] == "170"

    client.post("/admin/design", data={"csrf": token, "action": "preset:Dunkel"})  # Vorlage lässt Texte stehen
    assert theme.get_theme(db)["tagline"] == "Radio Energy Österreich"
    client.post("/admin/design", data={"csrf": token, "action": "reset"})
    assert theme.get_theme(db)["hero_size"] == "100"


def test_layout_variant_and_options(client, db):
    assert "lay-skin-classic" in client.get("/").text and "lay-steps-top" in client.get("/").text
    _login(client)
    token = _csrf(client, "/admin/design")
    r = client.post("/admin/design", data={"csrf": token, "action": "variant:ENERGY Neon", "with_colors": "on"},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/").text
    assert "lay-skin-neon" in page and "lay-steps-dots" in page and "lay-caps-upper" in page
    assert "--accent: #e6007e" in client.get("/theme.css").text
    assert "ENERGY Neon <span class=\"badge\">aktiv</span>" in client.get("/admin/design").text
    # Einzelne Option ändern, ungültiger Wert fällt auf Standard zurück
    r = client.post("/admin/design", data={"csrf": token, "action": "layout", **theme.variant_layout("ENERGY Neon"),
                                           "layout_steps": "side", "layout_width": "riesig"}, follow_redirects=False)
    page = client.get("/").text
    assert "lay-steps-side" in page and "lay-width-narrow" in page and "lay-skin-neon" in page
    # Speichern im Farb-/Schrift-Formular lässt das Layout unverändert
    client.post("/admin/design", data=_form(theme.get_theme(db), csrf=token, action="save", page_bg="#101010"))
    assert "lay-steps-side" in client.get("/").text


def test_layout_preview_only_for_admins(client, db):
    q = "/?layout_skin=neon&preset=ENERGY+Neon"
    assert "lay-skin-neon" not in client.get(q).text  # Besucher: Parameter werden ignoriert
    assert "#e6007e" not in client.get("/theme.css?preset=ENERGY+Neon").text
    _login(client)
    page = client.get(q).text
    assert "lay-skin-neon" in page and "preset=ENERGY+Neon" in page
    assert "--accent: #e6007e" in client.get("/theme.css?preset=ENERGY+Neon").text
    assert "lay-skin-classic" in client.get("/").text  # nichts gespeichert


def test_game_mode_variant(client, db):
    assert "gamify.js" not in client.get("/").text  # standardmäßig aus
    _login(client)
    token = _csrf(client, "/admin/design")
    client.post("/admin/design", data={"csrf": token, "action": "variant:Spielerisch"})
    page = client.get("/").text
    assert "lay-game-on" in page and "/static/gamify.js" in page
    assert client.get("/static/gamify.js").status_code == 200


def test_arcade_variant_loads_pixel_font(client, db):
    _login(client)
    token = _csrf(client, "/admin/design")
    client.post("/admin/design", data={"csrf": token, "action": "variant:Arcade", "with_colors": "on"})
    page = client.get("/").text
    assert "lay-skin-arcade" in page and "lay-game-on" in page
    assert "font-family: 'Press Start 2P'" in client.get("/fonts.css").text
    assert "--bg: #0b0a1f" in client.get("/theme.css").text
