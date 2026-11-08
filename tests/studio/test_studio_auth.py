"""Anmeldung, Sessions, Sperre, Einladungen, Passwort und Rollenverwaltung."""
from datetime import timedelta

import pytest

from studio.accounts import AccountError, create_invitation, create_user, update_user
from studio.models import Invitation, StudioUser, now

from .conftest import ADMIN, csrf_of, login


def test_login_and_logout(sclient):
    assert sclient.get("/", follow_redirects=False).headers["location"] == "/login"
    res = login(sclient, *ADMIN)
    assert res.status_code == 303 and res.headers["location"] == "/"
    assert "Arbeitsfläche" in sclient.get("/").text
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})
    assert sclient.get("/api/me").status_code == 401


def test_wrong_password_and_unknown_user(sclient):
    assert login(sclient, ADMIN[0], "falsch-falsch").status_code == 401
    assert login(sclient, "niemand@example.com", "egal-egal-egal").status_code == 401


def test_login_needs_csrf(sclient):
    res = sclient.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]}, follow_redirects=False)
    assert res.status_code == 403


def test_lockout_after_failed_attempts(sclient):
    for _ in range(8):
        login(sclient, ADMIN[0], "falsch-falsch")
    res = login(sclient, *ADMIN)  # auch mit richtigem Passwort gesperrt
    assert res.status_code == 429


def test_session_expires(sclient, monkeypatch):
    import time
    login(sclient, *ADMIN)
    assert sclient.get("/api/me").status_code == 200
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 13 * 3600)
    assert sclient.get("/api/me").status_code == 401


def test_deactivated_user_is_logged_out(sclient, sdb):
    user = create_user(sdb, "pro@example.com", "pro-passwort-1", "pro")
    login(sclient, "pro@example.com", "pro-passwort-1")
    assert sclient.get("/api/me").status_code == 200
    admin = sdb.query(StudioUser).filter_by(role="admin").one()
    update_user(sdb, admin, user, role="pro", active=False, quota_mb=100, export_limit=None, name="")
    assert sclient.get("/api/me").status_code == 401
    assert login(sclient, "pro@example.com", "pro-passwort-1").status_code == 401


def test_api_write_needs_csrf_header(sclient):
    login(sclient, *ADMIN)
    assert sclient.patch("/api/me", json={"name": "Ron"}).status_code == 403
    token = csrf_of(sclient, "/")
    res = sclient.patch("/api/me", json={"name": "Ron"}, headers={"X-CSRF-Token": token})
    assert res.status_code == 200 and res.json()["name"] == "Ron"


def test_invitation_flow(sclient, sdb):
    login(sclient, *ADMIN)
    res = sclient.post("/admin/invitations", data={"email": "Sprecher@Example.com", "role": "pro",
                                                   "csrf": csrf_of(sclient, "/admin/users")}, follow_redirects=True)
    assert "Einladungslink für sprecher@example.com" in res.text
    url = res.text.split('class="copy" readonly value="')[1].split('"')[0]
    path = url.split("http://testserver")[1]
    # Link nur einmal sichtbar
    assert "class=\"copy\"" not in sclient.get("/admin/users").text
    sclient.post("/logout", data={"csrf": csrf_of(sclient, "/")})

    assert "sprecher@example.com" in sclient.get(path).text
    csrf = csrf_of(sclient, path)
    bad = sclient.post(path, data={"password": "kurz", "password2": "kurz", "csrf": csrf})
    assert bad.status_code == 400 and "mindestens 10" in bad.text
    ok = sclient.post(path, data={"name": "Sprecher", "password": "sprecher-pw-1", "password2": "sprecher-pw-1",
                                  "csrf": csrf}, follow_redirects=False)
    assert ok.status_code == 303
    assert sclient.get("/api/me").json()["email"] == "sprecher@example.com"
    # Link ist danach verbraucht
    assert sclient.get(path).status_code == 404


def test_expired_and_revoked_invitations(sclient, sdb):
    inv, token = create_invitation(sdb, None, "alt@example.com")
    inv.expires_at = now() - timedelta(minutes=1)
    sdb.commit()
    assert sclient.get(f"/invite/{token}").status_code == 404
    inv2, token2 = create_invitation(sdb, None, "weg@example.com")
    inv2.revoked = True
    sdb.commit()
    res = sclient.post(f"/invite/{token2}", data={"password": "irgendwas-123", "password2": "irgendwas-123",
                                                  "csrf": csrf_of(sclient)})
    assert res.status_code == 404
    assert sdb.query(StudioUser).filter_by(email="weg@example.com").first() is None


def test_token_is_stored_hashed(sdb):
    _, token = create_invitation(sdb, None, "hash@example.com")
    stored = sdb.query(Invitation).one().token_hash
    assert token not in stored and len(stored) == 64


def test_invitation_for_existing_account_rejected(sdb):
    with pytest.raises(AccountError):
        create_invitation(sdb, None, ADMIN[0])


def test_password_change_logs_out_other_sessions(sdb):
    from fastapi.testclient import TestClient
    from studio.main import app
    with TestClient(app) as a, TestClient(app) as b:
        login(a, *ADMIN)
        login(b, *ADMIN)
        res = a.post("/account/password", data={"current": ADMIN[1], "password": "neues-passwort-9",
                                                "password2": "neues-passwort-9", "csrf": csrf_of(a, "/account")})
        assert res.status_code == 200 and "Passwort geändert" in res.text
        assert a.get("/api/me").status_code == 200
        assert b.get("/api/me").status_code == 401


def test_last_admin_cannot_be_demoted(sdb):
    admin = sdb.query(StudioUser).filter_by(role="admin").one()
    with pytest.raises(AccountError):
        update_user(sdb, admin, admin, role="pro", active=True, quota_mb=1, export_limit=None, name="")
    second = create_user(sdb, "zweiter@example.com", "zweiter-admin-1", "admin")
    update_user(sdb, second, admin, role="pro", active=True, quota_mb=1, export_limit=None, name="")
    assert admin.role == "pro"


def test_admin_edits_quota_via_form(sclient, sdb):
    user = create_user(sdb, "quota@example.com", "quota-passwort", "trial")
    login(sclient, *ADMIN)
    res = sclient.post(f"/admin/users/{user.id}", data={"role": "pro", "active": "1", "quota_mb": "500",
                                                       "export_limit": "20", "name": "Q",
                                                       "csrf": csrf_of(sclient, "/admin/users")}, follow_redirects=True)
    assert "gespeichert" in res.text
    sdb.refresh(user)
    assert (user.role, user.quota_mb, user.export_limit, user.name) == ("pro", 500, 20, "Q")


def test_cli_invite(sdb, capsys):
    from studio.cli import main
    assert main(["invite", "cli@example.com", "--role", "trial"]) == 0
    out = capsys.readouterr().out
    assert "/invite/" in out and "Testzugang" in out
