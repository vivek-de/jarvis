"""
backend/tools/implementations/datetime_tool.py — IST clock & market status (Phase 5, READ).
═══════════════════════════════════════════════════════════════════════════════
Queries:
  • "now"                  → current IST datetime + day of week
  • "market_status"        → NSE cash/F&O open? (Mon–Fri 09:15–15:30 IST)
  • "days_until:YYYY-MM-DD" → whole days from today (IST) to that date

Market status is a schedule check only (weekends are closed; NSE trading holidays are
NOT modelled here) — it's an aid, never a trading signal, and JARVIS places no orders.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from ..base import BaseTool, ToolPermission, ToolResult

IST = timezone(timedelta(hours=5, minutes=30))
_OPEN = time(9, 15)
_CLOSE = time(15, 30)


def _market_status(now: datetime) -> dict:
    is_weekday = now.weekday() < 5           # Mon=0 .. Fri=4
    within = _OPEN <= now.time() <= _CLOSE
    is_open = is_weekday and within
    if not is_weekday:
        note = "closed (weekend)"
    elif now.time() < _OPEN:
        note = "closed (pre-open; opens 09:15 IST)"
    elif now.time() > _CLOSE:
        note = "closed (after hours; closed 15:30 IST)"
    else:
        note = "open"
    return {"open": is_open, "note": note, "session": "09:15–15:30 IST Mon–Fri",
            "as_of": now.isoformat(),
            "caveat": "schedule only — NSE holidays not modelled; not a trading signal"}


class DatetimeTool(BaseTool):
    name = "datetime"
    description = ("Current IST date/time, day of week, NSE market open/close status, or "
                   "days until a date. query: 'now' | 'market_status' | 'days_until:YYYY-MM-DD'.")
    permission = ToolPermission.READ
    schema = {"type": "object",
              "properties": {"query": {"type": "string",
                                       "enum-ish": "now | market_status | days_until:YYYY-MM-DD"}},
              "required": ["query"]}

    def _run(self, args: dict) -> ToolResult:
        q = (args.get("query") or "now").strip().lower()
        now = datetime.now(IST)

        if q == "now":
            return ToolResult.success({
                "iso": now.isoformat(), "date": now.date().isoformat(),
                "time": now.strftime("%H:%M:%S"), "day_of_week": now.strftime("%A"),
                "tz": "IST (+05:30)"})

        if q in ("market_status", "market", "is_market_open"):
            return ToolResult.success(_market_status(now))

        if q.startswith("days_until:"):
            raw = q.split(":", 1)[1].strip()
            try:
                target = date.fromisoformat(raw)
            except ValueError:
                return ToolResult.fail(f"bad date '{raw}' — use days_until:YYYY-MM-DD")
            delta = (target - now.date()).days
            if delta > 0:
                phrase = f"{delta} day(s) from now"
            elif delta == 0:
                phrase = "today"
            else:
                phrase = f"{abs(delta)} day(s) ago"
            return ToolResult.success({"target": raw, "days": delta, "phrase": phrase})

        return ToolResult.fail("unknown query — use 'now', 'market_status', or 'days_until:YYYY-MM-DD'")
