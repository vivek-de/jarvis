#!/usr/bin/env python3
"""
scripts/migrate.py — apply all migrations (SQLite sessions + Postgres memory).
The app also auto-applies these on startup; this is for running/verifying them alone.
    python3 scripts/migrate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_settings          # noqa: E402
from backend.database.db import run_migrations as run_sqlite  # noqa: E402


def main() -> int:
    s = get_settings()

    applied = run_sqlite(s.db_file)
    print(f"SQLite ({s.db_file}): applied {applied or 'nothing new'}")

    if s.database_url:
        try:
            from backend.memory.pg import run_migrations as run_pg
            pg_applied = run_pg(s.database_url)
            print(f"Postgres ({s.database_url}): applied {pg_applied or 'nothing new'}")
        except Exception as e:
            print(f"Postgres migration FAILED: {e}")
            return 1
    else:
        print("Postgres: JARVIS_DATABASE_URL not set — skipping long-term memory migration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
