-- 003_scheduler.sql — JARVIS automation / scheduler (SQLite, Phase 9).
-- Lives in the SQLite migration set (same jarvis.db as sessions), NOT the Postgres
-- memory migrations: the scheduler store is SQLite. Datetimes are TEXT (ISO 8601, IST).

CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    name           TEXT    NOT NULL,
    trigger_type   TEXT    NOT NULL,          -- cron | interval | once
    trigger_value  TEXT    NOT NULL,          -- cron expr | seconds | ISO datetime
    action_type    TEXT    NOT NULL,          -- remind | message
    action_payload TEXT    NOT NULL DEFAULT '{}',   -- JSON
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_run       TEXT,
    next_run       TEXT,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(enabled, next_run);

CREATE TABLE IF NOT EXISTS reminders (
    id             TEXT PRIMARY KEY,
    task_id        TEXT,                       -- nullable; NULL = ad-hoc reminder
    message        TEXT    NOT NULL,
    scheduled_for  TEXT    NOT NULL,
    delivered      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(delivered, scheduled_for);
