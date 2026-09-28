"""
backend/scheduler/reminders.py — SQLite reminder store (Phase 9).
═══════════════════════════════════════════════════════════════════════════════
Reminders are the delivery side of the scheduler: a fired `remind` task (or a message
task's result) becomes a reminder row that the user picks up via /reminders/pending.
"""
from __future__ import annotations

import sqlite3
import uuid

from .triggers import now_ist

_COLS = "id, task_id, message, scheduled_for, delivered, created_at"


def _now() -> str:
    return now_ist().isoformat()


class ReminderStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """CREATE TABLE IF NOT EXISTS reminders (
                   id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL,
                   scheduled_for TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                   created_at TEXT NOT NULL);
               CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(delivered, scheduled_for);""")
        self.conn.commit()

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["delivered"] = bool(d["delivered"])
        return d

    def add_reminder(self, message: str, scheduled_for: str | None = None,
                     task_id: str | None = None) -> str:
        rid = str(uuid.uuid4())
        self.conn.execute(
            f"INSERT INTO reminders({_COLS}) VALUES (?,?,?,?,?,?)",
            (rid, task_id, message, scheduled_for or _now(), 0, _now()),
        )
        self.conn.commit()
        return rid

    def get_pending_reminders(self, now: str | None = None) -> list[dict]:
        now = now or _now()
        rows = self.conn.execute(
            f"""SELECT {_COLS} FROM reminders
                WHERE delivered=0 AND scheduled_for <= ? ORDER BY scheduled_for""",
            (now,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_delivered(self, reminder_id: str) -> int:
        cur = self.conn.execute("UPDATE reminders SET delivered=1 WHERE id=?", (reminder_id,))
        self.conn.commit()
        return cur.rowcount
