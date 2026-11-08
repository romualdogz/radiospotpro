import os
import re
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["STUDIO_DATABASE_URL"] = f"sqlite:///{_tmp}/studio-test.db"
os.environ["STUDIO_MEDIA_DIR"] = f"{_tmp}/studio-media"
os.environ["STUDIO_ADMIN_EMAIL"] = "ron@onaircraft.test"
os.environ["STUDIO_ADMIN_PASSWORD"] = "admin-passwort-123"
os.environ["STUDIO_SECRET_KEY"] = "studio-test"
os.environ.pop("STUDIO_HOSTS", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio.accounts import ensure_admin  # noqa: E402
from studio.database import Base, SessionLocal, engine, init_db  # noqa: E402
from studio.main import app  # noqa: E402
from studio.security import throttle  # noqa: E402

ADMIN = ("ron@onaircraft.test", "admin-passwort-123")


@pytest.fixture()
def sdb():
    init_db()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    throttle._hits.clear()
    with SessionLocal() as session:
        ensure_admin(session)
        yield session


@pytest.fixture()
def sclient(sdb):
    with TestClient(app) as c:
        yield c


def csrf_of(client: TestClient, path: str = "/login") -> str:
    html = client.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client: TestClient, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password, "csrf": csrf_of(client)},
                       follow_redirects=False)
