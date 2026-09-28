"""
backend/memory/dedupe.py — dedupe decision (Phase 3). Pure/stdlib, testable.
Before inserting a new memory, the store searches the same category for the most
similar existing memory; if cosine similarity ≥ threshold, update it instead of
inserting a near-duplicate.
"""
from __future__ import annotations


def is_duplicate(top_similarity: float | None, threshold: float = 0.92) -> bool:
    return top_similarity is not None and float(top_similarity) >= float(threshold)


def cosine_similarity(a, b) -> float:
    """Plain cosine similarity for two equal-length vectors (used in tests / fallbacks;
    production search uses pgvector's `<=>` operator in SQL)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
