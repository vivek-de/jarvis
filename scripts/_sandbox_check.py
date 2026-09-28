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

    print("[5] memory policy (Phase 2)")
    from backend.memory.policy import should_remember  # stdlib-only import
    check("secret never remembered", should_remember("my zerodha password is x").remember is False)
    check("explicit remember", should_remember("remember I prefer short replies").remember is True)
    check("preference", should_remember("always use IST, never notify at night").category == "preference")
    check("decision", should_remember("I decided to keep momentum on paper till mid-oct").category == "decision")
    check("deadline", should_remember("Amazon SDE-1 OA is on the 12th").category == "deadline")
    check("project status", should_remember("MarketGPT is built but write-up pending").category == "project")
    check("question not remembered", should_remember("what did I decide?").remember is False)
    check("chatter not remembered", should_remember("ok cool thanks").remember is False)
    check("correction wins (imp 5)", should_remember("actually the review is mid-nov").importance == 5)

    print("[6] identity files (Phase 2) — content, not OS-derived")
    idir = ROOT / "identity"
    user_md = (idir / "USER.md").read_text(encoding="utf-8") if (idir / "USER.md").exists() else ""
    soul_md = (idir / "SOUL.md").read_text(encoding="utf-8") if (idir / "SOUL.md").exists() else ""
    check("USER.md exists + names Vivek", "Vivek" in user_md)
    check("SOUL.md forbids OS-derived name", "never derive" in soul_md.lower() or "never infer" in soul_md.lower()
          or "os login" in soul_md.lower())
    check("SOUL.md carries read-only trading rule", "read-only" in soul_md.lower())

    print("[7] memory logic (Phase 3 — importance / commands / dedupe)")
    from backend.memory.commands import parse_command
    from backend.memory.dedupe import cosine_similarity, is_duplicate
    from backend.memory.importance import score_for
    check("importance correction=0.95", score_for("correction") == 0.95)
    check("importance preference=0.9", score_for("preference") == 0.9)
    check("importance project=0.8", score_for("project") == 0.8)
    check("importance chatter=0.1", score_for("chatter") == 0.1)
    check("importance default=0.5", score_for("???") == 0.5)
    check("cmd remember", (lambda c: c and c.kind == "remember")(parse_command("remember I trade NIFTY")))
    check("cmd recall", (lambda c: c and c.kind == "recall")(parse_command("what do you know about OptionIQ?")))
    check("cmd delete-all before forget", (lambda c: c and c.kind == "delete")(parse_command("delete everything about EcoCycle")))
    check("cmd forget", (lambda c: c and c.kind == "forget")(parse_command("forget my old note")))
    check("cmd none for chat", parse_command("how is the market?") is None)
    check("dedupe >=0.92 True", is_duplicate(0.93, 0.92) is True)
    check("dedupe <0.92 False", is_duplicate(0.90, 0.92) is False)
    check("cosine identical ~1", abs(cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9)

    print("[8] migration 002 SQL present + shaped")
    sql = (ROOT / "backend" / "memory" / "migrations" / "002_memories.sql").read_text()
    check("002 has vector(768)", "vector(768)" in sql)
    check("002 has HNSW index", "hnsw" in sql.lower() and "vector_cosine_ops" in sql)
    check("002 has superseded_by", "superseded_by" in sql)
    check("002 tracks migrations", "memory_schema_migrations" in sql)

    db.close()
    print(f"\nSANDBOX CHECK: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
