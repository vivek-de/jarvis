-- 001_init.sql — JARVIS Phase 1 schema (SQLite).
-- Versioned migration. Applied by backend/database/db.py. Idempotent-safe via IF NOT EXISTS.
-- Phase 3 will re-home this to Postgres via Alembic; keep SQL portable-ish.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- Conversations & messages (agent session history)
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,           -- uuid4
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('system','user','assistant')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

-- Per-LLM-call observability (model, tokens, latency, cost, success/failure)
CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id   TEXT,
    task_slot         TEXT,
    provider          TEXT,
    model             TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_inr          REAL DEFAULT 0,
    latency_ms        INTEGER DEFAULT 0,
    success           INTEGER DEFAULT 0,      -- 0/1
    error             TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_day ON llm_calls(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_provider ON llm_calls(provider, created_at);

-- Audit log (Phase 5 tool calls write here; table defined now so it's first-class)
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT,                          -- 'agent' | 'user' | 'scheduler'
    action      TEXT NOT NULL,
    detail      TEXT,                          -- JSON string
    permission  TEXT,                          -- READ|WRITE|FINANCIAL|-
    approved    INTEGER,                       -- 0/1/NULL
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_day ON audit_log(created_at);
