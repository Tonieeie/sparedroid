"""The AI example, with a fake Anthropic client (no network, no cost)."""

from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")

from examples import claude_qa  # noqa: E402
from wecomdroid import Message  # noqa: E402


class FakeClient:
    def __init__(self, text="", stop="end_turn", raises=None):
        self.calls = []
        self._resp = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])
        self._raises = raises
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self._raises:
            raise self._raises
        return self._resp


class FakeBot:
    def __init__(self):
        self.alerts = []

    def alert(self, text):
        self.alerts.append(text)


def ask(monkeypatch, client, body="你们几点上班？"):
    monkeypatch.setattr(claude_qa, "_client", lambda: client)
    bot = FakeBot()
    out = claude_qa.handle(Message("m", "群", "Alice", f"@bot {body}", body, True), bot)
    return out, bot


def test_answers_from_knowledge(monkeypatch):
    client = FakeClient("工作日 9 点到 18 点哦 😊")
    out, bot = ask(monkeypatch, client)
    assert out == "工作日 9 点到 18 点哦 😊" and bot.alerts == []
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "服务时间" in kw["system"][0]["text"]  # knowledge file is in the prompt


def test_handoff_alerts_team(monkeypatch):
    out, bot = ask(monkeypatch, FakeClient("HANDOFF"))
    assert out == claude_qa.HANDOFF and len(bot.alerts) == 1


def test_refusal_and_api_errors_become_handoff(monkeypatch):
    assert ask(monkeypatch, FakeClient("x", stop="refusal"))[0] == claude_qa.HANDOFF
    err = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="https://x"))
    assert ask(monkeypatch, FakeClient(raises=err))[0] == claude_qa.HANDOFF


def test_empty_question_does_not_call_the_api(monkeypatch):
    client = FakeClient("x")
    out, _ = ask(monkeypatch, client, body="  ")
    assert "@我" in out and client.calls == []
