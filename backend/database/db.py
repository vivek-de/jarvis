"""
backend/database/db.py — SQLite connection + versioned migration runner (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
Stdlib-only (sqlite3). Applies backend/database/migrations/*.sql in filename order,
recording each in schema_migrations so re-runs are safe. Also holds the small
data-access helpers used by the agent runtime.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may hop threads; our access is low-concurrency
    # and single-user, and WAL handles the rest.
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    if cur.fetchone() is None:
        return set()
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def run_migrations(db_file: Path) -> list[str]:
    """Apply any un-applied migrations. Returns the list of versions applied now."""
    conn = connect(db_file)
    applied_now: list[str] = []
    try:
        done = _applied_versions(conn)
        for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_path.stem  # e.g. "001_init"
            if version in done:
                continue
            conn.executescript(sql_path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?,?)",
                (version, _now()),
            )
            conn.commit()
            applied_now.append(version)
    finally:
        conn.close()
    return applied_now


# ── data-access helpers (used by agent.runtime) ─────────────────────────────
class DB:
    def __init__(self, db_file: Path):
        self.db_file = db_file
        self.conn = connect(db_file)

    def close(self) -> None:
        self.conn.close()

    # health
    def ping(self) -> bool:
        try:
            self.conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    # conversations
    def create_conversation(self, title: str | None = None) -> str:
        cid = str(uuid.uuid4())
        now = _now()
        self.conn.execute(
            "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (cid, title, now, now),
        )
        self.conn.commit()
        return cid

    def conversation_exists(self, cid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM conversations WHERE id=?", (cid,)
        ).fetchone() is not None

    def touch_conversation(self, cid: str) -> None:
        self.conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), cid))
        self.conn.commit()

    # messages
    def add_message(self, cid: str, role: str, content: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?,?,?,?)",
            (cid, role, content, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_messages(self, cid: str, limit: int | None = None) -> list[dict[str, Any]]:
        q = "SELECT role, content, created_at FROM messages WHERE conversation_id=? ORDER BY id"
        rows = self.conn.execute(q, (cid,)).fetchall()
        out = [dict(r) for r in rows]
        return out[-limit:] if limit else out

    # llm call log
    def log_llm_call(self, **kw: Any) -> None:
        self.conn.execute(
            """INSERT INTO llm_calls
               (conversation_id, task_slot, provider, model, prompt_tokens, completion_tokens,
                cost_inr, latency_ms, success, error, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                kw.get("conversation_id"), kw.get("task_slot"), kw.get("provider"), kw.get("model"),
                kw.get("prompt_tokens", 0), kw.get("completion_tokens", 0), kw.get("cost_inr", 0.0),
                kw.get("latency_ms", 0), 1 if kw.get("success") else 0, kw.get("error"), _now(),
            ),
        )
        self.conn.commit()
