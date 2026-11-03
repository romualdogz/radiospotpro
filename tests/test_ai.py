import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import ai

ARGS = dict(occasion="Event", seconds=20, tonality="emotional", style_instruction="Neutral.",
            firma="X", botschaft="Y", cta="Z")


def api_error(cls, status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls(message, response=response, body=None)


class FakeMessages:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok(text="Hallo Wien!"):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture()
def fake_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def install(*outcomes):
        beta, plain = FakeMessages(outcomes), FakeMessages(outcomes)
        # beide Wege teilen sich dieselbe Ergebnis-Liste
        plain.outcomes = beta.outcomes
        client = SimpleNamespace(beta=SimpleNamespace(messages=beta), messages=plain)
        monkeypatch.setattr(ai, "_get_client", lambda: client)
        return beta, plain
    return install


def run():
    return asyncio.run(ai.generate_script(**ARGS))


def test_success_uses_fallback(fake_client):
    beta, plain = fake_client(ok())
    assert run() == "Hallo Wien!"
    assert beta.calls[0]["fallbacks"] == "default" and not plain.calls


def test_retry_without_fallback_when_not_available(fake_client):
    beta, plain = fake_client(api_error(anthropic.BadRequestError, 400, "fallbacks: beta not enabled"), ok())
    assert run() == "Hallo Wien!"
    assert len(plain.calls) == 1 and "fallbacks" not in plain.calls[0]


@pytest.mark.parametrize("error,expected", [
    (api_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API."),
     "kein Guthaben"),
    (api_error(anthropic.NotFoundError, 404, "model not found"), "nicht verfügbar"),
    (api_error(anthropic.BadRequestError, 400, "This API key is not scoped to a workspace, so this request must "
               "include the anthropic-workspace-id header"), "Workspace"),
    (api_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "API-Key"),
    (api_error(anthropic.PermissionDeniedError, 403, "forbidden"), "keine Berechtigung"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "nicht erreichbar"),
])
def test_friendly_errors(fake_client, error, expected, caplog):
    fake_client(error)
    with pytest.raises(ai.ScriptError, match=expected):
        run()
    assert "Anthropic-Fehler" in caplog.text  # echte Ursache steht im Server-Log


def test_workspace_header(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_123")
    monkeypatch.setattr(ai, "_client", None)
    assert ai._get_client().default_headers["anthropic-workspace-id"] == "wrkspc_123"
    monkeypatch.setattr(ai, "_client", None)


def test_prompt_contains_audio_tag_instruction(fake_client):
    beta, _ = fake_client(ok("[excited] Neu!"), ok("Neu!"))
    asyncio.run(ai.generate_script(**ARGS, audio_tags=True, delivery_hint="energiegeladen – [excited]"))
    prompt = beta.calls[0]["messages"][0]["content"]
    assert "Eleven v4" in prompt and "energiegeladen – [excited]" in prompt
    asyncio.run(ai.generate_script(**ARGS, audio_tags=False))
    assert "Eleven v4" not in beta.calls[1]["messages"][0]["content"]


def test_three_variants_in_one_request(fake_client):
    beta, plain = fake_client(ok("<vorschlag>Eins</vorschlag>\n<vorschlag> Zwei </vorschlag><vorschlag>Drei</vorschlag>"))
    assert asyncio.run(ai.generate_scripts(**ARGS)) == ["Eins", "Zwei", "Drei"]
    assert len(beta.calls) == 1 and "3 deutlich unterschiedliche Varianten" in beta.calls[0]["messages"][0]["content"]


def test_variants_fallback_without_tags(fake_client):
    fake_client(ok("Nur ein Text ohne Tags"))
    assert asyncio.run(ai.generate_scripts(**ARGS)) == ["Nur ein Text ohne Tags"]
