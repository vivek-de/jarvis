-- 002_placement.sql — placement-prep structured data (UC4), SQLite.
-- Structured (dates/intervals) belongs in SQLite; semantic notes go to Postgres memory.

CREATE TABLE IF NOT EXISTS dsa_problems (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    topic         TEXT,
    difficulty    TEXT,                       -- easy | medium | hard
    status        TEXT,                       -- solved | struggled
    review_stage  INTEGER NOT NULL DEFAULT 0, -- 0→1d, 1→3d, 2→7d, 3→14d, 4=graduated
    next_review   TEXT,                       -- YYYY-MM-DD (IST); NULL once graduated
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dsa_next_review ON dsa_problems(next_review);

CREATE TABLE IF NOT EXISTS prep_deadlines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,                -- company / event
    due_date    TEXT NOT NULL,               -- YYYY-MM-DD (IST)
    kind        TEXT,                         -- OA | interview | other
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deadline_due ON prep_deadlines(due_date);
