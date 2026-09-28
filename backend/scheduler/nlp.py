"""
backend/scheduler/nlp.py — turn a natural-language request into a task spec (Phase 9).
═══════════════════════════════════════════════════════════════════════════════
Deterministic (regex) parsing — no LLM — so it's testable and predictable. Returns a
dict {name, trigger_type, trigger_value, action_type, action_payload} or None.

  "remind me at 9am every day to check markets" → cron "0 9 * * *", remind, "check markets"
  "remind me in 30 minutes to call Roshan"      → once (now+30m), remind, "call Roshan"
  "every morning give me my schedule"           → cron "0 9 * * 1-5", message, "my schedule"
"""
from __future__ import annotations

import re

from .triggers import now_ist

_IN_RE = re.compile(r"\bin\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b", re.I)
_MESSAGE_TAIL = re.compile(r"\bto\s+(.*)$", re.I)
_GIVE_ME = re.compile(r"\b(give|send|tell|show)\s+me\s+(.*)$", re.I)
_IS_MESSAGE = re.compile(r"\b(give|send|tell|show)\s+me\b", re.I)


def _message_of(text: str) -> str:
    m = _MESSAGE_TAIL.search(text)
    if m:
        return m.group(1).strip().rstrip(".")
    m = _GIVE_ME.search(text)
    if m:
        return m.group(2).strip().rstrip(".")
    return text.strip()


def _time_of_day(low: str) -> tuple[int | None, int]:
    for pat in (r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
                r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"):
        m = re.search(pat, low)
        if m:
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
            if ap == "am" and h == 12:
                h = 0
            elif ap == "pm" and h != 12:
                h += 12
            return h, mi
    return None, 0


def parse_schedule(text: str, now=None) -> dict | None:
    now = now or now_ist()
    low = text.lower()

    # ── relative one-shot: "in N minutes/hours/..." ──────────────────────────
    m = _IN_RE.search(low)
    if m:
        from datetime import timedelta
        n, raw = int(m.group(1)), m.group(2).lower()
        if raw.startswith(("second", "sec")):
            per = 1
        elif raw.startswith(("minute", "min")):
            per = 60
        elif raw.startswith(("hour", "hr")):
            per = 3600
        else:                                        # day(s)
            per = 86400
        when = now + timedelta(seconds=n * per)
        msg = _message_of(text)
        return {"name": f"reminder: {msg}"[:80], "trigger_type": "once",
                "trigger_value": when.isoformat(), "action_type": "remind",
                "action_payload": {"message": msg}}

    # ── recurring / scheduled ────────────────────────────────────────────────
    recurring = any(k in low for k in ("every day", "everyday", "every morning", "each morning",
                                       "every week", "weekly", "every weekday", "daily"))
    if recurring or "schedule" in low or "remind" in low:
        hour, minute = _time_of_day(low)
        if hour is None:
            hour, minute = 9, 0                     # sensible default: 9:00 IST
        if "weekday" in low or "morning" in low:
            dow = "1-5"
        elif "every week" in low or "weekly" in low:
            dow = str(now.isoweekday() % 7)         # cron dow: Sun=0
        else:
            dow = "*"
        cron = f"{minute} {hour} * * {dow}"
        msg = _message_of(text)
        action = "message" if _IS_MESSAGE.search(low) else "remind"
        return {"name": f"{action}: {msg}"[:80], "trigger_type": "cron",
                "trigger_value": cron, "action_type": action,
                "action_payload": {"message": msg}}

    return None
