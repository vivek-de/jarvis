-- 003_documents.sql — JARVIS document intelligence (Postgres + pgvector, Phase 8).
-- Same database as long-term memory; applied by backend/memory/pg.run_migrations.
-- documents = one row per uploaded file (SHA-256 unique → dedup); doc_chunks = the
-- embeddable pieces, cascade-deleted with their parent document.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id           uuid PRIMARY KEY,
    filename     text        NOT NULL,
    file_hash    text        NOT NULL UNIQUE,       -- SHA-256 of file bytes → dedup
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    doc_type     text,
    chunk_count  integer     NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS doc_chunks (
    id           uuid PRIMARY KEY,
    doc_id       uuid        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  integer     NOT NULL,
    content      text        NOT NULL,
    embedding    vector(768),                       -- NULL allowed: embed may fail, chunk still stored
    page_ref     text
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_hnsw
    ON doc_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc ON doc_chunks (doc_id);
