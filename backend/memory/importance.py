"""
backend/memory/importance.py — importance scoring for a memory (Phase 3).
Pure/stdlib so it's unit-testable. Maps the Phase-2 policy category to a 0.0–1.0
score used for retention and retrieval ranking.
"""
from __future__ import annotations

# Scores per the spec.
IMPORTANCE_BY_CATEGORY = {
    "correction": 0.95,
    "preference": 0.9,
    "deadline": 0.9,
    "decision": 0.85,
    "trading_discipline": 0.85,
    "project": 0.8,          # project_status
    "fact": 0.7,             # durable fact (not in the spec's list → sensible mid-high)
    "chatter": 0.1,
}
DEFAULT_IMPORTANCE = 0.5


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def score_for(category: str | None, override: float | None = None) -> float:
    """Importance for a category, or an explicit override (clamped to 0–1)."""
    if override is not None:
        return clamp01(override)
    return IMPORTANCE_BY_CATEGORY.get((category or "").lower(), DEFAULT_IMPORTANCE)
