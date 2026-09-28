"""
backend/memory/pg.py — Postgres connection + versioned migration runner (Phase 3).
Separate DB from the SQLite session store. Uses psycopg3 and registers the pgvector
type on each connection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url, autocommit=True)
    # Best-effort: registering pgvector adapters helps if we ever bind/read Vector
    # objects, but the store binds embeddings via explicit ::vector casts, so a missing
    # or mismatched pgvector build must NOT break the connection.
    try:
        from pgvector.psycopg import register_vector
        register_vector(conn)
    except Exception:
        pass
    return conn


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (name,))
        return cur.fetchone()[0] is not None


def run_migrations(database_url: str) -> list[str]:
    """Apply memory/migrations/*.sql not yet recorded. Returns versions applied now."""
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        done: set[str] = set()
        if _table_exists(conn, "memory_schema_migrations"):
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM memory_schema_migrations")
                done = {r[0] for r in cur.fetchall()}
        for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_path.stem
            if version in done:
                continue
            with conn.cursor() as cur:
                cur.execute(sql_path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO memory_schema_migrations(version, applied_at) VALUES (%s,%s) "
                    "ON CONFLICT (version) DO NOTHING",
                    (version, datetime.now(timezone.utc)),
                )
            applied_now.append(version)
    return applied_now
