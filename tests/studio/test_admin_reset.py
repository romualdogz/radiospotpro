"""Admin-Zugang per Terminal zurücksetzen (scripts/admin_reset.py)."""
import importlib.util
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from studio import totp
from studio.models import StudioUser, now
from studio.security import verify_password as studio_verify

from .conftest import ADMIN, csrf_of, login

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def reset(monkeypatch):
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("admin_reset", ROOT / "scripts" / "admin_reset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    os.chdir(cwd)


def test_studio_admin_locked_out_gets_back_in(sclient, sdb, reset, capsys):
    admin = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    admin.active, admin.valid_until = False, now() - timedelta(days=1)
    admin.totp_secret, admin.totp_enabled = totp.new_secret(), True
    sdb.commit()
    assert reset.main(["--studio", "--user", ADMIN[0], "--password", "neues-passwort-42"]) == 0
    assert "zurückgesetzt" in capsys.readouterr().out
    sdb.expire_all()
    admin = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    assert admin.active and admin.valid_until is None and not admin.totp_enabled and admin.role == "admin"
    assert studio_verify("neues-passwort-42", admin.password_hash)
    assert login(sclient, ADMIN[0], "neues-passwort-42").headers["location"] == "/"


def test_studio_admin_created_with_generated_password(sdb, reset, capsys):
    assert reset.main(["--studio", "--user", "Neu@Onaircraft.test", "--generate"]) == 0
    out = capsys.readouterr().out
    pw = out.split("Neues Passwort: ")[1].split()[0]
    user = sdb.query(StudioUser).filter_by(email="neu@onaircraft.test").one()
    assert "angelegt" in out and user.role == "admin" and studio_verify(pw, user.password_hash)


def test_configurator_admin_reset(db, client, reset, capsys):
    from app.models import AdminUser
    from app.security import verify_password
    assert reset.main(["--konfigurator", "--user", "admin", "--password", "konfig-passwort-1"]) == 0
    db.expire_all()
    user = db.query(AdminUser).filter_by(username="admin").one()
    assert verify_password("konfig-passwort-1", user.password_hash) and user.role == "admin"
    res = client.post("/admin/login", data={"username": "admin", "password": "konfig-passwort-1",
                                            "csrf": __import__("re").search(r'name="csrf" value="([^"]+)"',
                                                                            client.get("/admin/login").text).group(1)},
                      follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/admin"


def test_errors_and_list(sdb, db, reset, capsys):
    assert reset.main(["--studio", "--user", ADMIN[0], "--password", "kurz"]) == 1
    assert reset.main(["--studio", "--user", "keine-mail", "--password", "lang-genug-123"]) == 1
    assert reset.main(["--studio"]) == 1  # ohne Terminal: --user ist Pflicht
    assert reset.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert ADMIN[0] in out and "Konfigurator: admin" in out
