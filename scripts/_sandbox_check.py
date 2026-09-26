#!/usr/bin/env python3
"""
scripts/_sandbox_check.py — stdlib-only verification of the safety-critical logic.
═══════════════════════════════════════════════════════════════════════════════
Runs WITHOUT any third-party packages (no fastapi/httpx/pydantic), so it executes
in restricted environments where PyPI is unavailable. It exercises the pieces that
MUST be correct: DB migrations, the spend-cap tracker, and the model-router
fallback decisions. The full pytest suite (which needs fastapi/httpx) runs on the Mac.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.db import DB, run_migrations              # noqa: E402
from backend.models.routing_core import parse_slot, route_decision  # noqa: E402
from backend.models.spend import SpendTracker                   # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name}")


def _insert_cost(conn: sqlite3.Connection, provider: str, cost: float):
    conn.execute(
        "INSERT INTO llm_calls(provider, model, cost_inr, success, created_at) VALUES (?,?,?,1,?)",
        (provider, "m", cost, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "check.db"

    print("[1] migrations")
    applied = run_migrations(tmp)
    check("001_init applied", "001_init" in applied)
    check("re-run is idempotent", run_migrations(tmp) == [])
    db = DB(tmp)
    for t in ("conversations", "messages", "llm_calls", "audit_log", "schema_migrations"):
        row = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        check(f"table {t} exists", row is not None)

    print("[2] conversation persistence")
    cid = db.create_conversation("hi")
    db.add_message(cid, "user", "hello")
    db.add_message(cid, "assistant", "hi there")
    msgs = db.get_messages(cid)
    check("2 messages stored in order", len(msgs) == 2 and msgs[0]["role"] == "user")
    check("conversation_exists true", db.conversation_exists(cid))
    check("unknown conversation false", not db.conversation_exists("nope"))

    print("[3] spend cap (₹200/day)")
    st = SpendTracker(db.conn, cap_inr=200.0)
    check("empty day spend = 0", st.spent_today() == 0.0)
    check("under cap when empty", st.under_cap() is True)
    _insert_cost(db.conn, "anthropic", 150.0)
    check("spent_today = 150 after one call", abs(st.spent_today() - 150.0) < 1e-9)
    check("provider filter works", abs(st.spent_today("anthropic") - 150.0) < 1e-9)
    check("still under cap at 150", st.under_cap() is True)
    check("would_exceed(60) at 150 -> True", st.would_exceed(60.0) is True)
    _insert_cost(db.conn, "openai", 60.0)   # total 210 > 200
    check("over cap at 210", st.under_cap() is False)
    check("remaining() clamps to 0", st.remaining() == 0.0)

    print("[4] router fallback decisions")
    check("parse ollama bare", parse_slot("llama3.1:8b") == ("ollama", "llama3.1:8b"))
    check("parse cloud", parse_slot("anthropic:claude-x") == ("anthropic", "claude-x"))

    d = route_decision("GENERAL", "ollama:llama3.1:8b", "llama3.1:8b", has_key=True, under_cap=True)
    check("local slot -> ollama, no fallback", d.provider == "ollama" and not d.is_fallback)

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=False, under_cap=True)
    check("cloud without key -> fallback to ollama", d.provider == "ollama" and d.is_fallback and "No API key" in d.notice)

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=False)
    check("cloud over cap -> fallback to ollama", d.provider == "ollama" and d.is_fallback and "cap" in d.notice.lower())

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=True)
    check("cloud with key + budget -> cloud allowed", d.provider == "anthropic" and not d.is_fallback)

    db.close()
    print(f"\nSANDBOX CHECK: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
