import os

from app.config import _load_dotenv


def test_dotenv_tolerates_copy_mistakes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# Kommentar\n"
        "RS_TEST_MODEL=RS_TEST_MODEL=eleven_v4\n"
        'RS_TEST_KEY="sk-test-123"\n'
        "RS_TEST_PLAIN = wert mit leerzeichen \n"
        "RS_TEST_EMPTY=\n"
    )
    for k in ("RS_TEST_MODEL", "RS_TEST_KEY", "RS_TEST_PLAIN", "RS_TEST_EMPTY"):
        monkeypatch.delenv(k, raising=False)
    _load_dotenv(env)
    assert os.environ["RS_TEST_MODEL"] == "eleven_v4"
    assert os.environ["RS_TEST_KEY"] == "sk-test-123"
    assert os.environ["RS_TEST_PLAIN"] == "wert mit leerzeichen"
    assert os.environ["RS_TEST_EMPTY"] == ""
    for k in ("RS_TEST_MODEL", "RS_TEST_KEY", "RS_TEST_PLAIN", "RS_TEST_EMPTY"):
        os.environ.pop(k, None)
