"""
Postgres + pgvector integration tests (Phase 3).
Skipped automatically unless JARVIS_DATABASE_URL is set (i.e. runs on the Mac where
Postgres+pgvector exist). Uses fixed vectors — no Ollama needed — to test the store
in isolation: dedupe-update, search ranking, soft/hard delete. Cleans up after itself.
"""
import os
import uuid

import pytest

DB_URL = os.environ.get("JARVIS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DB_URL, reason="JARVIS_DATABASE_URL not set (run on the Mac)")

DIM = 768
CAT = "pytest_tmp"


def _vec(seed: float) -> list[float]:
    # deterministic unit-ish vector; index 0 carries the signal so we can control similarity
    v = [0.0] * DIM
    v[0] = 1.0
    v[1] = seed
    return v


@pytest.fixture
def store():
    from backend.memory.pg import connect, run_migrations
    from backend.memory.store import MemoryStore
    run_migrations(DB_URL)
    conn = connect(DB_URL)
    st = MemoryStore(conn, dedupe_threshold=0.92)
    # clean any leftovers from a prior run
    with conn.cursor() as cur:
        cur.execute("DELETE FROM memories WHERE category = %s", (CAT,))
    yield st
    with conn.cursor() as cur:
        cur.execute("DELETE FROM memories WHERE category = %s", (CAT,))
    conn.close()


def test_insert_then_dedupe_update(store):
    r1 = store.add("I prefer concise replies", CAT, _vec(0.01), importance=0.9)
    assert r1["action"] == "inserted"
    # near-identical vector in same category → should UPDATE, not insert
    r2 = store.add("I prefer very concise replies", CAT, _vec(0.011), importance=0.9)
    assert r2["action"] == "updated" and r2["id"] == r1["id"]
    assert store.count_active() >= 1


def test_search_ranking_and_soft_delete(store):
    a = store.add("alpha memory", CAT, _vec(0.02))
    store.add("beta memory very different", CAT, [0.0, 1.0] + [0.0] * (DIM - 2))
    hits = store.search(_vec(0.02), top_k=5, category_filter=CAT)
    assert hits and hits[0]["content"] == "alpha memory"
    store.soft_delete(a["id"])
    hits2 = store.search(_vec(0.02), top_k=5, category_filter=CAT)
    assert all(h["id"] != a["id"] for h in hits2)   # soft-deleted excluded


def test_hard_delete(store):
    m = store.add("temp fact", CAT, _vec(0.5))
    store.hard_delete(m["id"])
    hits = store.search(_vec(0.5), top_k=5, category_filter=CAT)
    assert all(h["id"] != m["id"] for h in hits)
