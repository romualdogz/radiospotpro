import os
import tempfile

# Eigene Test-DB, bevor die App importiert wird
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SEED_DEMO_DATA"] = "0"
os.environ["SECRET_KEY"] = "test"
os.environ["MEDIA_DIR"] = f"{_tmp}/media"
os.environ.pop("ELEVENLABS_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import ensure_admin, ensure_countries, ensure_legal_texts  # noqa: E402


@pytest.fixture()
def db():
    import shutil
    from app.branding import LOGO_DIR
    shutil.rmtree(LOGO_DIR, ignore_errors=True)  # Logos aus dem Ordner würden sonst automatisch verwendet
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        ensure_admin(session)
        ensure_countries(session)
        ensure_legal_texts(session)
        yield session


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c
