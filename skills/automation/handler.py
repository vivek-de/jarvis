"""
skills/automation/handler.py — Phase 9 handler.
Parses a natural-language scheduling request and creates a task in the SQLite task
store, or lists existing tasks. Deterministic parse (no LLM). Scheduled actions are
only JARVIS's own remind/message — never trading.
"""
from __future__ import annotations

_LIST_HINTS = ("list my reminder", "list my task", "my reminders", "my tasks",
               "what reminders", "what's scheduled", "whats scheduled")

_TYPE_LABEL = {"cron": "recurring", "interval": "repeating", "once": "one-time"}


async def handle(ctx, query: str) -> dict:
    q = query.strip()
    db = getattr(ctx, "db", None)
    if db is None:
        return {"reply": "Scheduler isn't available in this context.", "sub": "off"}

    from backend.scheduler.store import TaskStore
    store = TaskStore(db.conn)

    low = q.lower()

    # ── list intent ──────────────────────────────────────────────────────────
    if any(h in low for h in _LIST_HINTS):
        tasks = [t for t in store.list_tasks() if t["enabled"]]
        if not tasks:
            return {"reply": "You have no active scheduled tasks.", "sub": "list"}
        lines = []
        for t in tasks:
            msg = (t["action_payload"] or {}).get("message", t["name"])
            when = f"{t['trigger_type']}={t['trigger_value']}"
            nxt = f" next {t['next_run'][:16]}" if t.get("next_run") else ""
            lines.append(f"- {msg}  ({t['action_type']}, {when}{nxt})")
        return {"reply": "Your scheduled tasks:\n" + "\n".join(lines), "sub": "list"}

    # ── create intent ────────────────────────────────────────────────────────
    from backend.scheduler.nlp import parse_schedule
    spec = parse_schedule(q)
    if spec is None:
        return {"reply": "I couldn't work out a time from that. Try e.g. "
                         "\"remind me at 9am every day to check markets\" or "
                         "\"remind me in 30 minutes to call Roshan\".", "sub": "parse_fail"}

    task = store.create_task(
        name=spec["name"], trigger_type=spec["trigger_type"], trigger_value=spec["trigger_value"],
        action_type=spec["action_type"], action_payload=spec["action_payload"])

    msg = spec["action_payload"].get("message", spec["name"])
    kind = _TYPE_LABEL.get(spec["trigger_type"], spec["trigger_type"])
    when = task.get("next_run")
    when_txt = f" — next at {when[:16].replace('T', ' ')} IST" if when else ""
    return {"reply": f"Scheduled ({kind}, {spec['action_type']}): \"{msg}\"{when_txt}.", "sub": "create"}
