import re
from io import BytesIO

from PIL import Image
from pypdf import PdfReader

from app import branding
from app.models import QuoteRequest


def _png(w=200, h=50, color=(200, 0, 30, 255)) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><rect width="100" height="20"/></svg>'


def _admin(client):
    def csrf(path):
        return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)
    token = csrf("/admin/login")
    client.post("/admin/login", data={"username": "admin", "password": "test-password", "csrf": token})
    return csrf("/admin/design")


def test_upload_shows_logo_in_configurator_and_legal(client, db):
    token = _admin(client)
    assert 'class="wordmark"' in client.get("/").text
    r = client.post("/admin/design/logo", data={"csrf": token, "height": "56", "in_pdf": "on", "action": "upload"},
                    files={"logo": ("logo.png", _png(), "image/png")})
    assert "Logo gespeichert" in r.text
    page = client.get("/").text
    url = re.search(r'<img class="logo" src="([^"]+)"[^>]*height: 56px', page).group(1)
    assert 'class="wordmark"' not in page
    assert '<img class="logo"' in client.get("/agb").text
    img = client.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert "default-src 'none'" in img.headers["content-security-policy"]


def test_replace_and_remove_deletes_old_files(client, db):
    token = _admin(client)
    client.post("/admin/design/logo", data={"csrf": token, "action": "upload"},
                files={"logo": ("a.png", _png(), "image/png")})
    first = branding.get_logo(db)["path"]
    client.post("/admin/design/logo", data={"csrf": token, "action": "upload"},
                files={"logo": ("b.svg", SVG, "image/svg+xml")})
    logo = branding.get_logo(db)
    assert not first.exists() and logo["path"].suffix == ".svg" and not logo["pdf_capable"]
    client.post("/admin/design/logo", data={"csrf": token, "action": "remove"})
    assert branding.get_logo(db) is None and not logo["path"].exists()
    assert 'class="wordmark"' in client.get("/").text


def test_rejects_invalid_files(client, db):
    token = _admin(client)
    for name, content, msg in [("x.gif", b"GIF89a", "PNG, JPG, WebP oder SVG"),
                               ("x.png", b"kein bild", "nicht als Bild"),
                               ("x.jpg", _png(), "passen nicht zusammen"),
                               ("x.svg", b"<html></html>", "keine SVG"),
                               ("x.png", b"\x89PNG" + b"0" * (branding.MAX_BYTES + 10), "größer als 2 MB")]:
        r = client.post("/admin/design/logo", data={"csrf": token, "action": "upload"},
                        files={"logo": (name, content, "application/octet-stream")})
        assert msg in r.text, name
    assert branding.get_logo(db) is None
    assert client.get("/media/logo/..%2F..%2Fapp%2Fmain.py").status_code == 404


def test_logo_in_pdf_and_switch(client, db):
    token = _admin(client)
    client.post("/admin/design/logo", data={"csrf": token, "action": "upload", "in_pdf": "on"},
                files={"logo": ("logo.png", _png(), "image/png")})
    req = QuoteRequest(customer_name="Max", email="m@example.com", configuration={}, brief={}, quote={})
    db.add(req)
    db.commit()

    def images():
        pdf = client.get(f"/admin/requests/{req.id}/pdf").content
        return len(PdfReader(BytesIO(pdf)).pages[0].images)

    assert images() == 1
    client.post("/admin/design/logo", data={"csrf": token, "action": "upload"})  # Häkchen aus
    assert images() == 0


def test_sales_cannot_upload_logo(client, db):
    from app.models import AdminUser
    from app.security import hash_password
    db.add(AdminUser(username="verkauf", password_hash=hash_password("verkauf-passwort"), role="sales"))
    db.commit()
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    client.post("/admin/login", data={"username": "verkauf", "password": "verkauf-passwort", "csrf": token})
    r = client.post("/admin/design/logo", data={"csrf": token, "action": "upload"},
                    files={"logo": ("logo.png", _png(), "image/png")})
    assert r.status_code == 403 and branding.get_logo(db) is None


def test_logo_placed_in_folder_is_used_until_removed(client, db):
    import shutil
    from pathlib import Path
    branding.LOGO_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).parent.parent / "media" / "logos" / "energy-logo.svg",
                branding.LOGO_DIR / "Energy Logo.svg")
    logo = branding.get_logo(db)
    assert logo["file"] == "Energy Logo.svg" and logo["url"] == "/media/logo/Energy%20Logo.svg"
    assert logo["height"] == branding.HEIGHT_DEFAULT_TALL  # fast quadratisch → größer dargestellt
    assert '<img class="logo" src="/media/logo/Energy%20Logo.svg"' in client.get("/").text
    assert client.get(logo["url"]).headers["content-type"] == "image/svg+xml"
    token = _admin(client)
    client.post("/admin/design/logo", data={"csrf": token, "action": "remove"})
    assert branding.get_logo(db) is None and 'class="wordmark"' in client.get("/").text
    assert (branding.LOGO_DIR / "Energy Logo.svg").exists()  # von Hand abgelegte Datei bleibt
