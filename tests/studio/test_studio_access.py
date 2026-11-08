"""Zugriffsschutz: ohne Login ist im Studio nichts erreichbar – Seiten wie API."""
from datetime import timedelta

from fastapi.routing import APIRoute

from studio.accounts import create_invitation, create_user
from studio import api, pages
from studio.main import app
from studio.models import Invitation, StudioUser, now

from .conftest import ADMIN, csrf_of, login

PUBLIC = {"/login", "/logout", "/invite/{token}", "/health"}


def _fill(path: str) -> str:
    return path.replace("{token}", "x").replace("{user_id}", "1").replace("{inv_id}", "1")


def _routes():
    """Alle Routen der App (die eingebundenen Router direkt, unabhängig von FastAPI-Interna)."""
    found = [r for router in (pages.router, api.router, app.router) for r in router.routes if isinstance(r, APIRoute)]
    assert len(found) >= 12, "Routen nicht gefunden"
    return found


def test_every_api_route_requires_login(sclient):
    api_routes = [r for r in _routes() if r.path.startswith("/api")]
    assert len(api_routes) >= 3
    for r in api_routes:
        for method in r.methods:
            res = sclient.request(method, _fill(r.path))
            assert res.status_code == 401, f"{method} {r.path} ohne Login: {res.status_code}"


def test_every_page_requires_login(sclient):
    for r in _routes():
        if r.path.startswith("/api") or r.path in PUBLIC:
            continue
        for method in r.methods:
            res = sclient.request(method, _fill(r.path), follow_redirects=False)
            # GET → Weiterleitung zur Anmeldung; POST ohne CSRF/Session → abgelehnt
            assert res.status_code in (303, 403), f"{method} {r.path}: {res.status_code}"
            if res.status_code == 303:
                assert res.headers["location"] == "/login"


def test_no_public_registration_or_docs(sclient):
    for path in ("/register", "/signup", "/docs", "/openapi.json", "/redoc"):
        assert sclient.get(path, follow_redirects=False).status_code == 404, path


def test_pro_user_cannot_reach_admin(sclient, sdb):
    create_user(sdb, "kollege@example.com", "kollegen-pw-123", "pro")
    assert login(sclient, "kollege@example.com", "kollegen-pw-123").status_code == 303
    assert sclient.get("/").status_code == 200
    assert sclient.get("/admin/users").status_code == 403
    assert sclient.get("/api/admin/users").status_code == 403
    assert sclient.get("/api/me").json()["role"] == "pro"


def test_admin_api_lists_users(sclient):
    login(sclient, *ADMIN)
    emails = [u["email"] for u in sclient.get("/api/admin/users").json()]
    assert emails == [ADMIN[0]]


def test_security_headers_and_cookie(sclient):
    res = login(sclient, *ADMIN)
    cookie = res.headers["set-cookie"]
    assert cookie.startswith("studio_session=") and "httponly" in cookie.lower()
    page = sclient.get("/")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY"


def test_configurator_cookie_is_not_accepted(sclient):
    """Das Studio hat ein eigenes Cookie mit eigenem Schlüssel – das Konfigurator-Cookie öffnet nichts."""
    from itsdangerous import TimestampSigner
    import base64, json
    payload = base64.b64encode(json.dumps({"uid": 1, "epoch": 0, "exp": 9999999999}).encode())
    forged = TimestampSigner("test").sign(payload).decode()  # Schlüssel des Konfigurators in den Tests
    sclient.cookies.set("studio_session", forged)
    assert sclient.get("/api/me").status_code == 401


def test_trusted_hosts(monkeypatch):
    from starlette.applications import Starlette
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from fastapi.testclient import TestClient
    inner = Starlette(routes=[Route("/", lambda r: PlainTextResponse("ok"))])
    guarded = TrustedHostMiddleware(inner, allowed_hosts=["studio.onaircraft.net"])
    c = TestClient(guarded)
    assert c.get("/", headers={"host": "studio.onaircraft.net"}).status_code == 200
    assert c.get("/", headers={"host": "onaircraft.net"}).status_code == 400
