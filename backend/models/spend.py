"""
backend/models/spend.py — daily spend tracking + cap (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
Sums cloud-LLM cost per IST calendar day from the llm_calls table and enforces a
configurable ₹/day cap. Local (Ollama) calls cost ₹0 and never count against it.
Stdlib-only (sqlite3) so the safety logic is trivially testable and auditable.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_day_bounds_utc(now_utc: datetime | None = None) -> tuple[str, str]:
    """Return [start,end) of the current IST day expressed as UTC ISO strings."""
    now_utc = now_utc or datetime.now(timezone.utc)
    ist_now = now_utc.astimezone(IST)
    start_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ist = start_ist + timedelta(days=1)
    return start_ist.astimezone(timezone.utc).isoformat(), end_ist.astimezone(timezone.utc).isoformat()


class SpendTracker:
    def __init__(self, conn: sqlite3.Connection, cap_inr: float):
        self.conn = conn
        self.cap_inr = float(cap_inr)

    def spent_today(self, provider: str | None = None) -> float:
        start, end = _ist_day_bounds_utc()
        q = "SELECT COALESCE(SUM(cost_inr),0) FROM llm_calls WHERE created_at >= ? AND created_at < ?"
        args: list = [start, end]
        if provider:
            q += " AND provider = ?"
            args.append(provider)
        return float(self.conn.execute(q, args).fetchone()[0] or 0.0)

    def remaining(self) -> float:
        return max(0.0, self.cap_inr - self.spent_today())

    def under_cap(self) -> bool:
        return self.spent_today() < self.cap_inr

    def would_exceed(self, prospective_cost_inr: float) -> bool:
        return (self.spent_today() + max(0.0, prospective_cost_inr)) > self.cap_inr
