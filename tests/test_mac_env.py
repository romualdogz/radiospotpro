import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def env_tool(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mac_env", ROOT / "scripts" / "mac_env.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(mod, "ENV", tmp_path / ".env")
    monkeypatch.setattr(mod, "EXAMPLE", tmp_path / ".env.example")
    return mod


def test_create_with_random_secrets(env_tool):
    assert env_tool.ensure() == "created"
    values = env_tool._values(env_tool._read(env_tool.ENV))
    assert len(values["SECRET_KEY"]) > 40 and values["SECRET_KEY"] != "change-me"
    assert len(values["ADMIN_PASSWORD"]) >= 16 and values["ADMIN_PASSWORD"] != "change-me-too"
    assert values["SMTP_HOST"] == "" and values["ELEVENLABS_MODEL"] == "eleven_v4"
    assert oct(env_tool.ENV.stat().st_mode & 0o777) == "0o600"


def test_update_keeps_values_and_adds_missing(env_tool):
    env_tool.ENV.write_text("# alt\nSECRET_KEY=change-me\nADMIN_PASSWORD=geheim\nELEVENLABS_API_KEY=sk_x\n")
    result = env_tool.ensure()
    assert result.startswith("updated:") and int(result.split(":")[1]) > 5
    text = env_tool.ENV.read_text()
    values = env_tool._values(text.splitlines())
    assert values["ADMIN_PASSWORD"] == "geheim" and values["ELEVENLABS_API_KEY"] == "sk_x"
    assert values["SECRET_KEY"] != "change-me"  # unsicherer Platzhalter wird ersetzt
    assert "SMTP_HOST" in values and "# alt" in text and "ergänzt vom Installer" in text
    assert env_tool.ensure() == "updated:0"  # zweiter Lauf ändert nichts


def test_set_and_get(env_tool, capsys):
    env_tool.ensure()
    env_tool.main(["set", "SMTP_HOST=smtp.gmail.com", "SMTP_PASSWORD=a b=c", "NEU=1"])
    env_tool.main(["get", "SMTP_PASSWORD"])
    assert capsys.readouterr().out.strip() == "a b=c"
    values = env_tool._values(env_tool._read(env_tool.ENV))
    assert values["SMTP_HOST"] == "smtp.gmail.com" and values["NEU"] == "1"
    assert list(values).count("SMTP_HOST") == 1


def test_config_loader_reads_generated_env(env_tool, monkeypatch):
    """Was der Installer schreibt, muss der tolerante .env-Loader der App genauso lesen."""
    env_tool.ensure()
    env_tool.main(["set", "SMTP_PASSWORD=abc def"])
    from app import config
    for key in ("SMTP_PASSWORD", "SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    config._load_dotenv(env_tool.ENV)
    import os
    assert os.environ["SMTP_PASSWORD"] == "abc def"
    assert os.environ["SECRET_KEY"] == env_tool._values(env_tool._read(env_tool.ENV))["SECRET_KEY"]
