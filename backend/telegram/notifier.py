"""
backend/telegram/notifier.py — outbound Telegram push (Phase 10).
═══════════════════════════════════════════════════════════════════════════════
Thin wrapper over the Telegram Bot API sendMessage endpoint, used by the scheduler
to push reminders. Deliberately graceful: if the token or chat_id is missing, or the
HTTP call fails for any reason, it logs and returns False — it NEVER raises, so a
Telegram outage can't break the scheduler loop. httpx is imported lazily.
"""
from __future__ import annotations

from ..logging_setup import get_logger

log = get_logger("jarvis.telegram")

DEFAULT_API = "https://api.telegram.org"
SEND_TIMEOUT_S = 10


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, api_base: str = DEFAULT_API):
        self.token = token or ""
        self.chat_id = str(chat_id or "")
        self.api_base = api_base.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send_message(self, text: str) -> bool:
        if not self.enabled:
            log.warning("telegram.notify_skipped", extra={"reason": "token/chat_id not set"})
            return False
        url = f"{self.api_base}/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}
        try:
            import httpx
        except Exception as e:
            log.warning("telegram.httpx_missing", extra={"error": str(e)})
            return False
        try:
            async with httpx.AsyncClient(timeout=SEND_TIMEOUT_S) as client:
                resp = await client.post(url, json=payload)
        except Exception as e:                    # network error → graceful False
            log.warning("telegram.notify_failed", extra={"error": str(e)})
            return False
        if resp.status_code != 200:
            log.warning("telegram.notify_http", extra={"status": resp.status_code})
            return False
        return True
