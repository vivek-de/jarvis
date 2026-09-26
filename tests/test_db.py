from backend.database.db import DB, run_migrations


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    dbf = tmp_path / "m.db"
    applied = run_migrations(dbf)
    assert "001_init" in applied
    assert run_migrations(dbf) == []          # second run applies nothing


def test_conversation_and_messages_persist(tmp_path):
    dbf = tmp_path / "m2.db"
    run_migrations(dbf)
    db = DB(dbf)
    cid = db.create_conversation("test")
    assert db.conversation_exists(cid)
    db.add_message(cid, "user", "hi")
    db.add_message(cid, "assistant", "hello")
    msgs = db.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hi"
    db.close()


def test_llm_call_logged(tmp_path):
    dbf = tmp_path / "m3.db"
    run_migrations(dbf)
    db = DB(dbf)
    db.log_llm_call(provider="ollama", model="llama3.1:8b", success=True,
                    prompt_tokens=3, completion_tokens=7, cost_inr=0.0, latency_ms=42)
    row = db.conn.execute("SELECT provider, success, completion_tokens FROM llm_calls").fetchone()
    assert row["provider"] == "ollama" and row["success"] == 1 and row["completion_tokens"] == 7
    db.close()
