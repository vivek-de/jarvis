"""Phase 10 — Telegram: notifier (mock httpx) + bot (fake update objects).

No real network and no python-telegram-bot needed: the notifier's httpx call is
monkeypatched, and the bot handlers are dependency-light (they only touch
update.effective_chat/user/message), so fake update objects drive them directly.
"""
import asyncio

import pytest

from backend.telegram.bot import TelegramBot, format_reminders, format_tasks
from backend.telegram.notifier import TelegramNotifier


# ══ notifier ══════════════════════════════════════════════════════════════════
class FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def _patch_httpx(monkeypatch, status=200, raise_exc=False, calls=None):
    httpx = pytest.importorskip("httpx")

    class FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            if calls is not None:
                calls.append((url, json))
            if raise_exc:
                raise RuntimeError("network down")
            return FakeResp(status)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)


def test_notifier_sends_correct_payload(monkeypatch):
    calls = []
    _patch_httpx(monkeypatch, status=200, calls=calls)
    n = TelegramNotifier("TOK", "999")
    ok = asyncio.run(n.send_message("hello"))
    assert ok is True and len(calls) == 1
    url, payload = calls[0]
    assert url == "https://api.telegram.org/botTOK/sendMessage"
    assert payload == {"chat_id": "999", "text": "hello"}


def test_notifier_skips_without_token():
    calls_would_be = TelegramNotifier("", "999")
    assert calls_would_be.enabled is False
    assert asyncio.run(calls_would_be.send_message("x")) is False


def test_notifier_skips_without_chat_id():
    assert asyncio.run(TelegramNotifier("TOK", "").send_message("x")) is False


def test_notifier_http_error_returns_false(monkeypatch):
    _patch_httpx(monkeypatch, status=500)
    assert asyncio.run(TelegramNotifier("TOK", "1").send_message("x")) is False


def test_notifier_network_exception_returns_false(monkeypatch):
    _patch_httpx(monkeypatch, raise_exc=True)
    assert asyncio.run(TelegramNotifier("TOK", "1").send_message("x")) is False


# ══ bot: fakes ════════════════════════════════════════════════════════════════
class FakeMsg:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, t):
        self.sent.append(t)


class _Obj:
    def __init__(self, id):
        self.id = id


class FakeUpdate:
    def __init__(self, chat_id, text="hi", user_id=1):
        self.effective_chat = _Obj(chat_id)
        self.effective_user = _Obj(user_id)
        self.message = FakeMsg(text)


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def chat(self, message, channel=None):
        self.calls.append((message, channel))
        return {"reply": f"echo: {message}"}


class FakeReminders:
    def get_pending_reminders(self):
        return [{"message": "check markets"}, {"message": "call Roshan"}]


class FakeTasks:
    def list_tasks(self):
        return [{"name": "n", "enabled": True, "action_type": "remind",
                 "trigger_type": "cron", "trigger_value": "0 9 * * *",
                 "action_payload": {"message": "check markets"}}]


def _bot(agent=None):
    return TelegramBot("TOK", "123", agent=agent or FakeAgent(),
                       task_store=FakeTasks(), reminder_store=FakeReminders())


# ══ bot: behavior ═════════════════════════════════════════════════════════════
def test_bot_ignores_unauthorized_chat():
    bot = _bot()
    upd = FakeUpdate(chat_id=999, text="hi")          # not the configured 123
    asyncio.run(bot.on_text(upd))
    assert upd.message.sent == [] and bot.agent.calls == []


def test_bot_routes_message_to_agent():
    bot = _bot()
    upd = FakeUpdate(chat_id=123, text="what's up")
    asyncio.run(bot.on_text(upd))
    assert bot.agent.calls == [("what's up", "telegram")]
    assert upd.message.sent == ["echo: what's up"]


def test_bot_start_sends_welcome():
    bot = _bot()
    upd = FakeUpdate(chat_id=123)
    asyncio.run(bot.on_start(upd))
    assert upd.message.sent and "JARVIS" in upd.message.sent[0]


def test_bot_start_unauthorized_silent():
    bot = _bot()
    upd = FakeUpdate(chat_id=5)
    asyncio.run(bot.on_start(upd))
    assert upd.message.sent == []


def test_bot_rate_limits_second_message():
    bot = _bot()

    async def run():
        await bot.on_text(FakeUpdate(chat_id=123, text="one", user_id=7))
        await bot.on_text(FakeUpdate(chat_id=123, text="two", user_id=7))

    asyncio.run(run())
    assert len(bot.agent.calls) == 1                  # 2nd within 3s dropped


def test_bot_reminders_command():
    bot = _bot()
    upd = FakeUpdate(chat_id=123)
    asyncio.run(bot.on_reminders(upd))
    assert "check markets" in upd.message.sent[0] and "call Roshan" in upd.message.sent[0]


def test_bot_tasks_command():
    bot = _bot()
    upd = FakeUpdate(chat_id=123)
    asyncio.run(bot.on_tasks(upd))
    assert "check markets" in upd.message.sent[0] and "cron" in upd.message.sent[0]


def test_bot_agent_error_sends_fallback():
    class BadAgent:
        calls = []

        async def chat(self, message, channel=None):
            raise RuntimeError("boom")

    bot = TelegramBot("TOK", "123", agent=BadAgent(), task_store=FakeTasks(),
                      reminder_store=FakeReminders())
    upd = FakeUpdate(chat_id=123, text="hi")
    asyncio.run(bot.on_text(upd))
    assert upd.message.sent and "went wrong" in upd.message.sent[0].lower()


# ══ formatting ════════════════════════════════════════════════════════════════
def test_format_reminders_empty_and_nonempty():
    assert "No pending" in format_reminders([])
    out = format_reminders([{"message": "a"}, {"message": "b"}])
    assert "• a" in out and "• b" in out


def test_format_tasks_skips_disabled():
    tasks = [{"name": "on", "enabled": True, "action_type": "remind",
              "trigger_type": "cron", "trigger_value": "0 9 * * *",
              "action_payload": {"message": "hi"}},
             {"name": "off", "enabled": False, "action_type": "remind",
              "trigger_type": "cron", "trigger_value": "0 9 * * *", "action_payload": {}}]
    out = format_tasks(tasks)
    assert "hi" in out and "off" not in out
    assert "No active" in format_tasks([])
