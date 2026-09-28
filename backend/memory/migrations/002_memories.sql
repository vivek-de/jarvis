-- 002_memories.sql — JARVIS long-term memory (Postgres + pgvector, Phase 3).
-- Applied by backend/memory/pg.py against JARVIS_DATABASE_URL. Separate DB from the
-- SQLite conversation-session store. The `vector` extension is created by the operator
-- (CREATE EXTENSION vector) during setup; included here too so a fresh DB is complete.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id             uuid PRIMARY KEY,
    content        text        NOT NULL,
    category       text        NOT NULL,
    importance     real        NOT NULL DEFAULT 0.5,   -- 0.0–1.0
    source         text,                                -- user | journal | scheduler | ...
    embedding      vector(768),                         -- nomic-embed-text dimension
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    superseded_by  uuid        NULL REFERENCES memories(id)  -- NULL = active; self = soft-deleted; other = replaced
);

-- Approximate-NN index for semantic search (cosine distance).
CREATE INDEX IF NOT EXISTS idx_memories_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Fast category filtering over active memories only.
CREATE INDEX IF NOT EXISTS idx_memories_active_category
    ON memories (category) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS memory_schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
