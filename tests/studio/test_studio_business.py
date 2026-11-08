"""Schritt 5: Laufzeit/Abrechnung, Testzugang, Verbrauchsübersicht, Einladung per E-Mail,
„An onaircraft schicken“, Zwei-Faktor-Anmeldung."""
import re
import time
from datetime import timedelta

import pytest

from studio import mail, totp
from studio.accounts import accept_invitation, create_invitation, create_user
from studio.models import Asset, Project, StudioUser, SupportRequest, aware, now

from .conftest import ADMIN, csrf_of, login
from .test_studio_editor import project_with_clip, run_queue, tone, upload

PRO = ("pro@example.com", "pro-passwort-1")


def _h(client):
    return {"X-CSRF-Token": csrf_of(client, "/")}


def _logout(client):
    client.post("/logout", data={"csrf": csrf_of(client, "/")})


# --------------------------------------------------------------------------- Laufzeit & Abrechnung

def test_trial_invitation_expires_automatically(sdb):
    _, token = create_invitation(sdb, None, "test@example.com", "trial")
    user = accept_invitation(sdb, token, "test-passwort-1")
    assert aware(user.valid_until) - now() == pytest.approx(timedelta(days=14), abs=timedelta(minutes=1))
    _, token = create_invitation(sdb, None, "pro2@example.com", "pro")
    assert accept_invitation(sdb, token, "pro-passwort-12").valid_until is None


def test_expired_account_is_read_only(sclient, sdb):
    user = create_user(sdb, *PRO, "pro")
    h = _h(sclient) if login(sclient, *PRO) else None
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    ex = sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h).json()
    run_queue()
    user.valid_until = now() - timedelta(days=1)
    sdb.commit()
    page = sclient.get("/").text
    assert "abgelaufen" in page
    me = sclient.get("/api/me").json()
    assert me["expired"] is True
    for res in (upload(sclient, h), sclient.post(f"/api/projects/{pid}/exports", json={}, headers=h),
                sclient.post("/api/ai/script", json={"occasion": "A", "botschaft": "B"}, headers=h),
                sclient.post("/api/ai/voice", json={"voice_id": 1, "text": "Hi"}, headers=h)):
        assert res.status_code == 403 and "abgelaufen" in res.json()["detail"]
    # ansehen, speichern und herunterladen geht weiter
    assert sclient.get(f"/api/projects/{pid}").status_code == 200
    assert sclient.get(f"/api/exports/{ex['id']}/download").status_code == 200


def test_admin_detail_page_saves_billing(sclient, sdb):
    user = create_user(sdb, *PRO, "pro")
    login(sclient, *ADMIN)
    page = sclient.get(f"/admin/users/{user.id}")
    assert page.status_code == 200 and "Abrechnung" in page.text
    res = sclient.post(f"/admin/users/{user.id}", data={
        "role": "pro", "active": "1", "name": "Kollege", "quota_mb": "500", "export_limit": "50",
        "tts_chars_month": "10000", "scripts_month": "20", "valid_until": "2030-12-31", "plan": "Pro jährlich",
        "billing_note": "Rechnung 2026-17 bezahlt", "csrf": csrf_of(sclient, f"/admin/users/{user.id}")},
        follow_redirects=True)
    assert "gespeichert" in res.text
    sdb.refresh(user)
    assert (user.plan, user.billing_note, aware(user.valid_until).strftime("%Y-%m-%d")) == \
        ("Pro jährlich", "Rechnung 2026-17 bezahlt", "2030-12-31")
    bad = sclient.post(f"/admin/users/{user.id}", data={"role": "pro", "quota_mb": "1", "valid_until": "31.12.",
                                                       "csrf": csrf_of(sclient, "/admin/users")})
    assert bad.status_code == 400


def test_users_overview_shows_usage(sclient, sdb):
    login(sclient, *ADMIN)
    upload(sclient, _h(sclient))
    page = sclient.get("/admin/users").text
    assert re.search(r"0 / 2000 MB", page) and "aktiv" in page


# --------------------------------------------------------------------------- Einladung per E-Mail

def test_invitation_sent_by_mail(sclient, sdb, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "enabled", lambda: True)
    monkeypatch.setattr(mail.mailer, "send", lambda msg: sent.append(msg))
    login(sclient, *ADMIN)
    res = sclient.post("/admin/invitations", data={"email": "neu@example.com", "role": "trial", "send_mail": "1",
                                                   "csrf": csrf_of(sclient, "/admin/users")}, follow_redirects=True)
    assert "Per E-Mail verschickt" in res.text
    assert sent and sent[0]["To"] == "neu@example.com"
    body = sent[0].get_content()
    assert "/invite/" in body and "Testzugang" in body


def test_invitation_mail_error_keeps_link(sclient, monkeypatch):
    monkeypatch.setattr(mail, "enabled", lambda: True)
    def boom(msg):
        raise mail.mailer.MailError("Server weg")
    monkeypatch.setattr(mail.mailer, "send", boom)
    login(sclient, *ADMIN)
    res = sclient.post("/admin/invitations", data={"email": "x@example.com", "role": "pro", "send_mail": "1",
                                                   "csrf": csrf_of(sclient, "/admin/users")}, follow_redirects=True)
    assert "Server weg" in res.text and "/invite/" in res.text


# --------------------------------------------------------------------------- An onaircraft schicken

def test_support_request_and_copy(sclient, sdb, monkeypatch):
    create_user(sdb, *PRO, "pro")
    login(sclient, *PRO)
    h = _h(sclient)
    a = upload(sclient, h).json()
    pid = project_with_clip(sclient, h, a["id"])
    res = sclient.post(f"/api/projects/{pid}/support", json={"message": "Bitte mit echtem Sprecher"}, headers=h)
    assert res.status_code == 201 and res.json()["notified"] is False
    assert sclient.get("/admin/support").status_code == 403
    _logout(sclient)

    login(sclient, *ADMIN)
    page = sclient.get("/admin/support").text
    assert "Bitte mit echtem Sprecher" in page and "pro@example.com" in page
    req = sdb.query(SupportRequest).one()
    res = sclient.post(f"/admin/support/{req.id}/copy", data={"csrf": csrf_of(sclient, "/admin/support")},
                       follow_redirects=True)
    assert "Kopie" in res.text
    sdb.expire_all()
    admin = sdb.query(StudioUser).filter_by(email=ADMIN[0]).one()
    copy = sdb.query(Project).filter_by(user_id=admin.id).one()
    copied_asset = sdb.query(Asset).filter_by(user_id=admin.id).one()
    assert copy.data["clips"][0]["asset_id"] == copied_asset.id and copy.name.startswith("pro@example.com")
    assert sdb.get(SupportRequest, req.id).status == "in Arbeit"
    # Kopie lässt sich exportieren, Original bleibt beim Kunden
    ex = sclient.post(f"/api/projects/{copy.id}/exports", json={}, headers=_h(sclient)).json()
    run_queue()
    assert sclient.get(f"/api/exports/{ex['id']}").json()["status"] == "done"
    assert sdb.get(Project, pid).user_id != admin.id
    # zweiter Klick legt keine zweite Kopie an
    sclient.post(f"/admin/support/{req.id}/copy", data={"csrf": csrf_of(sclient, "/admin/support")})
    assert sdb.query(Project).filter_by(user_id=admin.id).count() == 1
    sclient.post(f"/admin/support/{req.id}/status", data={"status": "erledigt", "csrf": csrf_of(sclient, "/admin/support")})
    sdb.expire_all()
    assert sdb.get(SupportRequest, req.id).status == "erledigt"


def test_support_notification_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "enabled", lambda: True)
    monkeypatch.setattr(mail.mailer, "send", lambda msg: sent.append(msg))
    object.__setattr__(mail.settings, "support_email", "studio@onaircraft.test")
    try:
        assert mail.notify_support("k@example.com", "Spot", "Hilfe", "http://x/admin/support") is True
    finally:
        object.__setattr__(mail.settings, "support_email", "")
    assert sent[0]["To"] == "studio@onaircraft.test" and "Hilfe" in sent[0].get_content()


# --------------------------------------------------------------------------- Zwei-Faktor-Anmeldung

def _enable_2fa(client) -> str:
    client.post("/account/2fa/start", data={"csrf": csrf_of(client, "/account")})
    page = client.get("/account").text
    secret = re.search(r'<code class="mono">([A-Z2-7 ]+)</code>', page).group(1).replace(" ", "")
    assert "data:image/svg+xml;base64," in page
    bad = client.post("/account/2fa/confirm", data={"code": "000000", "csrf": csrf_of(client, "/account")})
    assert bad.status_code == 400
    code = totp.code_at(secret, int(time.time() // 30))
    res = client.post("/account/2fa/confirm", data={"code": code, "csrf": csrf_of(client, "/account")}, follow_redirects=True)
    assert "eingeschaltet" in res.text
    return secret


def test_two_factor_login(sclient, sdb):
    create_user(sdb, *PRO, "pro")
    login(sclient, *PRO)
    secret = _enable_2fa(sclient)
    _logout(sclient)

    res = login(sclient, *PRO)
    assert res.headers["location"] == "/login/2fa"
    assert sclient.get("/api/me").status_code == 401          # Passwort allein reicht nicht
    form = csrf_of(sclient, "/login/2fa")
    assert sclient.post("/login/2fa", data={"code": "123456", "csrf": form}).status_code == 401
    # Code, der bei der Einrichtung schon benutzt wurde, gilt nicht noch einmal → nächstes Zeitfenster
    step = int(time.time() // 30) + 1
    code = totp.code_at(secret, step)
    res = sclient.post("/login/2fa", data={"code": code, "csrf": form}, follow_redirects=False)
    assert res.status_code == 303 and sclient.get("/api/me").status_code == 200
    _logout(sclient)
    login(sclient, *PRO)
    replay = sclient.post("/login/2fa", data={"code": code, "csrf": csrf_of(sclient, "/login/2fa")})
    assert replay.status_code == 401                            # derselbe Code nicht zweimal


def test_admin_resets_two_factor(sclient, sdb):
    user = create_user(sdb, *PRO, "pro")
    login(sclient, *PRO)
    _enable_2fa(sclient)
    _logout(sclient)
    login(sclient, *ADMIN)
    page = sclient.get("/admin/users").text
    assert "2FA" in page
    sclient.post(f"/admin/users/{user.id}/reset-2fa", data={"csrf": csrf_of(sclient, f"/admin/users/{user.id}")})
    sdb.refresh(user)
    assert not user.totp_enabled and user.totp_secret is None
    _logout(sclient)
    assert login(sclient, *PRO).headers["location"] == "/"


def test_two_factor_pending_session_expires(sclient, sdb, monkeypatch):
    create_user(sdb, *PRO, "pro")
    login(sclient, *PRO)
    _enable_2fa(sclient)
    _logout(sclient)
    login(sclient, *PRO)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 600)
    assert sclient.get("/login/2fa", follow_redirects=False).headers["location"] == "/login"


def test_totp_rfc_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30) == "287082"          # RFC 6238, gekürzt auf 6 Stellen
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None
