"""
backend/scheduler/store.py — SQLite task store (Phase 9).
═══════════════════════════════════════════════════════════════════════════════
CRUD over the `tasks` table plus get_due_tasks (enabled AND next_run ≤ now). Uses the
shared jarvis.db SQLite connection. ensure_schema() makes the store usable on any
connection (tests, standalone) even before migrations run. action_payload is stored
as JSON text and returned as a dict.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from ..logging_setup import get_logger
from .triggers import compute_next_run, now_ist

log = get_logger("jarvis.scheduler")

_COLS = "id, name, trigger_type, trigger_value, action_type, action_payload, enabled, last_run, next_run, created_at"
_UPDATABLE = {"name", "trigger_type", "trigger_value", "action_type", "action_payload", "enabled", "next_run", "last_run"}


def _now() -> str:
    return now_ist().isoformat()


class TaskStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """CREATE TABLE IF NOT EXISTS tasks (
                   id TEXT PRIMARY KEY, name TEXT NOT NULL, trigger_type TEXT NOT NULL,
                   trigger_value TEXT NOT NULL, action_type TEXT NOT NULL,
                   action_payload TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
                   last_run TEXT, next_run TEXT, created_at TEXT NOT NULL);
               CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(enabled, next_run);""")
        self.conn.commit()

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        try:
            d["action_payload"] = json.loads(d["action_payload"] or "{}")
        except Exception:
            d["action_payload"] = {}
        return d

    def create_task(self, name: str, trigger_type: str, trigger_value, action_type: str,
                    action_payload: dict | None = None, enabled: bool = True,
                    next_run: str | None = None) -> dict:
        tid = str(uuid.uuid4())
        if next_run is None and enabled:
            try:
                next_run = compute_next_run(trigger_type, trigger_value)
            except Exception as e:   # e.g. croniter missing — task still stored, just not due
                log.warning("scheduler.next_run_failed", extra={"error": str(e)})
                next_run = None
        self.conn.execute(
            f"INSERT INTO tasks({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, name, trigger_type, str(trigger_value), action_type,
             json.dumps(action_payload or {}), 1 if enabled else 0, None, next_run, _now()),
        )
        self.conn.commit()
        return self.get_task(tid)

    def get_task(self, tid: str) -> dict | None:
        r = self.conn.execute(f"SELECT {_COLS} FROM tasks WHERE id=?", (tid,)).fetchone()
        return self._row(r) if r else None

    def list_tasks(self) -> list[dict]:
        rows = self.conn.execute(f"SELECT {_COLS} FROM tasks ORDER BY created_at").fetchall()
        return [self._row(r) for r in rows]

    def update_task(self, tid: str, **fields) -> dict | None:
        if self.get_task(tid) is None:
            return None
        sets, params = [], []
        recompute = ("trigger_type" in fields or "trigger_value" in fields) and "next_run" not in fields
        for k, v in fields.items():
            if k not in _UPDATABLE:
                continue
            if k == "action_payload":
                v = json.dumps(v or {})
            elif k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k}=?")
            params.append(v)
        if sets:
            params.append(tid)
            self.conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()

        if recompute:
            cur = self.get_task(tid)
            if cur["enabled"]:
                try:
                    nxt = compute_next_run(cur["trigger_type"], cur["trigger_value"])
                except Exception as e:
                    log.warning("scheduler.next_run_failed", extra={"error": str(e)})
                    nxt = None
                self.conn.execute("UPDATE tasks SET next_run=? WHERE id=?", (nxt, tid))
                self.conn.commit()
        return self.get_task(tid)

    def delete_task(self, tid: str) -> int:
        cur = self.conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.conn.commit()
        return cur.rowcount

    def get_due_tasks(self, now: str | None = None) -> list[dict]:
        now = now or _now()
        rows = self.conn.execute(
            f"""SELECT {_COLS} FROM tasks
                WHERE enabled=1 AND next_run IS NOT NULL AND next_run <= ?
                ORDER BY next_run""",
            (now,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_ran(self, tid: str, last_run: str, next_run: str | None) -> None:
        self.conn.execute("UPDATE tasks SET last_run=?, next_run=? WHERE id=?",
                          (last_run, next_run, tid))
        self.conn.commit()
