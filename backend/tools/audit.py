"""
backend/tools/audit.py — every tool call is recorded (Phase 5).
═══════════════════════════════════════════════════════════════════════════════
Two sinks, best-effort (auditing must never break a tool call):
  • SQLite  audit_log table  (durable, queryable — table exists since migration 001)
  • logs/tools.log           (one human-readable line per call)

args_summary is a SHORT string — never dump raw file contents or secrets into the log.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("jarvis.tools")
# backend/tools/audit.py → parents[2] = project root
ROOT = Path(__file__).resolve().parents[2]
TOOLS_LOG = ROOT / "logs" / "tools.log"


def log_tool_call(conn: sqlite3.Connection | None, tool_name: str, permission: str,
                  args_summary: str, result_ok: bool, error: str | None = None,
                  latency_ms: int = 0) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    detail = json.dumps({"tool": tool_name, "args": args_summary,
                         "ok": result_ok, "error": error, "latency_ms": latency_ms})

    # 1) SQLite audit_log (actor='agent', action='tool_call')
    if conn is not None:
        try:
            conn.execute(
                "INSERT INTO audit_log(actor, action, detail, permission, approved, created_at) "
                "VALUES (?,?,?,?,?,?)",
                ("agent", "tool_call", detail, permission, 1 if result_ok else 0, ts),
            )
            conn.commit()
        except Exception as e:  # never let auditing break the call
            log.warning("audit.sqlite_failed", extra={"tool": tool_name, "error": str(e)})

    # 2) logs/tools.log (one line)
    status = "OK" if result_ok else f"ERR({error})"
    line = f"{ts} {permission:9} {tool_name:14} {status} {latency_ms}ms :: {args_summary}\n"
    try:
        TOOLS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TOOLS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as e:
        log.warning("audit.file_failed", extra={"tool": tool_name, "error": str(e)})
