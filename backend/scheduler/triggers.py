"""
backend/scheduler/triggers.py — compute a task's next fire time (Phase 9).
═══════════════════════════════════════════════════════════════════════════════
Everything runs in IST (the user's timezone) so "9am" means 9am for Vivek. next_run
is an ISO string with the +05:30 offset, which compares lexicographically the same way
it compares chronologically — so get_due_tasks can use a plain string `<=`.

  • interval → after + N seconds
  • once     → the given datetime if still in the future, else None (one-shot)
  • cron     → croniter (imported lazily; raises a clear error if not installed)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def _iso(dt: datetime) -> str:
    return dt.astimezone(IST).isoformat()


def parse_dt(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


def compute_next_run(trigger_type: str, trigger_value, after: datetime | None = None) -> str | None:
    after = after or now_ist()
    t = (trigger_type or "").lower()

    if t == "interval":
        return _iso(after + timedelta(seconds=int(float(trigger_value))))

    if t == "once":
        dt = parse_dt(trigger_value)
        return _iso(dt) if dt > after else None

    if t == "cron":
        try:
            from croniter import croniter
        except Exception as e:                       # dep missing → surface clearly
            raise RuntimeError(f"croniter not installed: {e}")
        if not croniter.is_valid(trigger_value):
            raise ValueError(f"invalid cron expression: {trigger_value!r}")
        return _iso(croniter(trigger_value, after).get_next(datetime))

    raise ValueError(f"unknown trigger_type: {trigger_type!r}")


def validate_trigger(trigger_type: str, trigger_value) -> str | None:
    """Return an error string if the trigger is invalid, else None (croniter optional)."""
    t = (trigger_type or "").lower()
    if t not in ("cron", "interval", "once"):
        return f"trigger_type must be cron|interval|once, got {trigger_type!r}"
    try:
        if t == "interval":
            if int(float(trigger_value)) <= 0:
                return "interval seconds must be positive"
        elif t == "once":
            parse_dt(trigger_value)
        elif t == "cron":
            try:
                from croniter import croniter
                if not croniter.is_valid(trigger_value):
                    return f"invalid cron expression: {trigger_value!r}"
            except Exception:
                pass   # croniter absent → accept; engine will report at run time
    except Exception as e:
        return f"bad trigger_value for {t}: {e}"
    return None
