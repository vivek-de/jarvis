from backend.config import Settings
from backend.database.db import DB, run_migrations
from backend.models.router import ModelRouter
from backend.models.routing_core import parse_slot, route_decision
from backend.models.spend import SpendTracker


def test_parse_slot_handles_colon_in_model():
    assert parse_slot("llama3.1:8b") == ("ollama", "llama3.1:8b")   # bare ollama model w/ colon
    assert parse_slot("ollama:llama3.1:8b") == ("ollama", "llama3.1:8b")
    assert parse_slot("anthropic:claude-x") == ("anthropic", "claude-x")


def test_route_decision_matrix():
    d = route_decision("G", "ollama:llama3.1:8b", "llama3.1:8b", has_key=True, under_cap=True)
    assert d.provider == "ollama" and not d.is_fallback

    d = route_decision("G", "anthropic:claude-x", "llama3.1:8b", has_key=False, under_cap=True)
    assert d.provider == "ollama" and d.is_fallback and "key" in d.notice.lower()

    d = route_decision("G", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=False)
    assert d.provider == "ollama" and d.is_fallback and "cap" in d.notice.lower()

    d = route_decision("G", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=True)
    assert d.provider == "anthropic" and not d.is_fallback


def test_model_router_resolve_local(tmp_path):
    dbf = tmp_path / "r.db"
    run_migrations(dbf)
    db = DB(dbf)
    s = Settings(_env_file=None)
    router = ModelRouter(s, SpendTracker(db.conn, 200.0))
    dec = router.resolve("GENERAL")
    assert dec.provider == "ollama" and dec.model == "llama3.1:8b"
    db.close()


def test_model_router_falls_back_without_key(tmp_path):
    dbf = tmp_path / "r2.db"
    run_migrations(dbf)
    db = DB(dbf)
    s = Settings(_env_file=None, model_coding="anthropic:claude-x")  # no key set
    router = ModelRouter(s, SpendTracker(db.conn, 200.0))
    dec = router.resolve("CODING")
    assert dec.provider == "ollama" and dec.is_fallback
    db.close()
