from datetime import datetime, timezone

from backend.database.db import DB, run_migrations
from backend.models.spend import SpendTracker


def _cost(db, provider, amt):
    db.conn.execute(
        "INSERT INTO llm_calls(provider, model, cost_inr, success, created_at) VALUES (?,?,?,1,?)",
        (provider, "m", amt, datetime.now(timezone.utc).isoformat()),
    )
    db.conn.commit()


def test_spend_cap_refusal(tmp_path):
    dbf = tmp_path / "s.db"
    run_migrations(dbf)
    db = DB(dbf)
    st = SpendTracker(db.conn, cap_inr=200.0)

    assert st.spent_today() == 0.0
    assert st.under_cap() is True

    _cost(db, "anthropic", 150.0)
    assert st.spent_today() == 150.0
    assert st.spent_today("anthropic") == 150.0
    assert st.under_cap() is True
    assert st.would_exceed(60.0) is True     # 150+60 > 200

    _cost(db, "openai", 60.0)                 # total 210
    assert st.under_cap() is False            # cap enforced → cloud refused, fallback to LOCAL
    assert st.remaining() == 0.0
    db.close()


def test_local_calls_do_not_count(tmp_path):
    dbf = tmp_path / "s2.db"
    run_migrations(dbf)
    db = DB(dbf)
    st = SpendTracker(db.conn, cap_inr=10.0)
    # ollama calls are logged with cost 0 → never move the needle
    for _ in range(100):
        _cost(db, "ollama", 0.0)
    assert st.spent_today() == 0.0
    assert st.under_cap() is True
    db.close()
