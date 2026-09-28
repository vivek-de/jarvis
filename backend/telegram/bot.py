"""
backend/telegram/bot.py — inbound Telegram bot (Phase 10).
═══════════════════════════════════════════════════════════════════════════════
Uses python-telegram-bot (v21+, async), imported lazily so this module loads without
the dependency (sandbox / notifier-only deployments).

Security: the bot serves ONLY the configured chat_id. Messages from any other chat are
silently ignored — no reply, no agent call, no data leak. A per-user rate limit (1 msg
/ 3s) keeps a chatty client from hammering the agent.

Commands: /start (welcome), /reminders (pending reminders), /tasks (scheduled tasks).
Any other text is routed to the JARVIS agent (channel="telegram") and the reply sent back.
The bot is read-only over trading and never places orders — it's just a chat front-end.
"""
from __future__ import annotations

import time

from ..logging_setup import get_logger

log = get_logger("jarvis.telegram")

WELCOME = ("JARVIS online. Ask me anything, or use /reminders and /tasks.\n"
           "I'm read-only on trading — I never place orders.")
RATE_LIMIT_SECONDS = 3.0


def format_reminders(reminders: list[dict]) -> str:
    if not reminders:
        return "No pending reminders."
    lines = [f"• {r.get('message', '')}" for r in reminders]
    return "Pending reminders:\n" + "\n".join(lines)


def format_tasks(tasks: list[dict]) -> str:
    active = [t for t in tasks if t.get("enabled", True)]
    if not active:
        return "No active scheduled tasks."
    lines = []
    for t in active:
        msg = (t.get("action_payload") or {}).get("message", t.get("name", ""))
        when = f"{t.get('trigger_type')}={t.get('trigger_value')}"
        lines.append(f"• {msg}  ({t.get('action_type')}, {when})")
    return "Scheduled tasks:\n" + "\n".join(lines)


class TelegramBot:
    def __init__(self, token: str, chat_id: str, agent=None, task_store=None,
                 reminder_store=None, rate_limit_seconds: float = RATE_LIMIT_SECONDS):
        self.token = token
        self.chat_id = str(chat_id or "")
        self.agent = agent
        self.tasks = task_store
        self.reminders = reminder_store
        self.rate_limit_seconds = rate_limit_seconds
        self._last_seen: dict[int, float] = {}
        self._app = None

    # ── authorization + rate limit ───────────────────────────────────────────
    def _authorized(self, update) -> bool:
        chat = getattr(update, "effective_chat", None)
        return chat is not None and str(getattr(chat, "id", "")) == self.chat_id

    def _rate_limited(self, user_id: int, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        last = self._last_seen.get(user_id)
        if last is not None and (now - last) < self.rate_limit_seconds:
            return True
        self._last_seen[user_id] = now
        return False

    # ── handlers (update, context) — kept dependency-light for testing ────────
    async def on_start(self, update, context=None) -> None:
        if not self._authorized(update):
            log.info("telegram.ignored_unauthorized", extra={"cmd": "start"})
            return
        await update.message.reply_text(WELCOME)

    async def on_text(self, update, context=None) -> None:
        if not self._authorized(update):
            log.info("telegram.ignored_unauthorized", extra={"cmd": "text"})
            return
        uid = getattr(getattr(update, "effective_user", None), "id", 0)
        if self._rate_limited(uid):
            log.info("telegram.rate_limited", extra={"user": uid})
            return
        text = getattr(update.message, "text", "") or ""
        if not text.strip():
            return
        try:
            out = await self.agent.chat(text, channel="telegram")
            reply = out.get("reply", "(no reply)")
        except Exception as e:
            log.warning("telegram.agent_failed", extra={"error": str(e)})
            reply = "⚠️ Something went wrong handling that."
        await update.message.reply_text(reply)

    async def on_reminders(self, update, context=None) -> None:
        if not self._authorized(update):
            return
        pending = self.reminders.get_pending_reminders() if self.reminders else []
        await update.message.reply_text(format_reminders(pending))

    async def on_tasks(self, update, context=None) -> None:
        if not self._authorized(update):
            return
        tasks = self.tasks.list_tasks() if self.tasks else []
        await update.message.reply_text(format_tasks(tasks))

    # ── lifecycle (lazy PTB import) ──────────────────────────────────────────
    def build(self):
        from telegram.ext import (Application, CommandHandler, MessageHandler,
                                   filters)
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.on_start))
        app.add_handler(CommandHandler("reminders", self.on_reminders))
        app.add_handler(CommandHandler("tasks", self.on_tasks))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        self._app = app
        return app

    async def start(self) -> None:
        if not self.token:
            log.warning("telegram.bot_disabled", extra={"reason": "no token"})
            return
        app = self.build()
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram.bot_started")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            if self._app.updater is not None:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            log.info("telegram.bot_stopped")
        except Exception as e:
            log.warning("telegram.bot_stop_failed", extra={"error": str(e)})
        finally:
            self._app = None
