"""
backend/memory/store.py — pgvector-backed long-term memory store (Phase 3).
CRUD + semantic search + dedupe. Cosine distance via `<=>`; similarity = 1 - distance.
`superseded_by`: NULL = active, self-id = soft-deleted, other-id = replaced.

Embeddings are bound as an explicit `%s::vector` cast from a pgvector text literal
('[0.1,0.2,...]'). This is adapter-independent — it does NOT rely on psycopg knowing
how to adapt a Python list to the `vector` type, which is the usual cause of a silent
"could not adapt" / type-mismatch failure on insert.
"""
from __future__ import annotations

import uuid
from typing import Any

import psycopg

from .dedupe import is_duplicate


def _vec_literal(embedding) -> str:
    """Python sequence → pgvector text literal, e.g. [0.1, 0.2] → '[0.1,0.2]'."""
    return "[" + ",".join(format(float(x), ".8g") for x in embedding) + "]"


class MemoryStore:
    def __init__(self, conn: psycopg.Connection, dedupe_threshold: float = 0.92):
        self.conn = conn
        self.dedupe_threshold = dedupe_threshold

    # ── create (with dedupe) ─────────────────────────────────────────────────
    def add(self, content: str, category: str, embedding, importance: float = 0.5,
            source: str = "user") -> dict[str, Any]:
        top = self._nearest_in_category(category, embedding)
        if top and is_duplicate(top["similarity"], self.dedupe_threshold):
            self.update(top["id"], content=content, importance=importance, embedding=embedding)
            return {"id": top["id"], "action": "updated", "similarity": top["similarity"]}

        mid = uuid.uuid4()
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO memories(id, content, category, importance, source, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s::vector)""",
                (mid, content, category, importance, source, _vec_literal(embedding)),
            )
        return {"id": mid, "action": "inserted", "similarity": (top or {}).get("similarity")}

    def _nearest_in_category(self, category: str, embedding) -> dict | None:
        lit = _vec_literal(embedding)
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, content, 1 - (embedding <=> %s::vector) AS similarity
                   FROM memories
                   WHERE superseded_by IS NULL AND category = %s AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector LIMIT 1""",
                (lit, category, lit),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "content": row[1], "similarity": float(row[2])}

    # ── read ─────────────────────────────────────────────────────────────────
    def search(self, query_embedding, top_k: int = 5, category_filter: str | None = None,
               min_similarity: float | None = None) -> list[dict]:
        lit = _vec_literal(query_embedding)
        params: list = [lit]
        where = "superseded_by IS NULL AND embedding IS NOT NULL"
        if category_filter:
            where += " AND category = %s"
            params.append(category_filter)
        params.append(lit)
        params.append(top_k)
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, content, category, importance, source,
                           1 - (embedding <=> %s::vector) AS similarity, created_at
                    FROM memories WHERE {where}
                    ORDER BY embedding <=> %s::vector LIMIT %s""",
                params,
            )
            rows = cur.fetchall()
        out = [{"id": r[0], "content": r[1], "category": r[2], "importance": float(r[3]),
                "source": r[4], "similarity": float(r[5]), "created_at": r[6]} for r in rows]
        if min_similarity is not None:
            out = [m for m in out if m["similarity"] >= min_similarity]
        return out

    def get_by_category(self, category: str) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, content, category, importance, source, created_at
                   FROM memories WHERE superseded_by IS NULL AND category = %s
                   ORDER BY importance DESC, updated_at DESC""",
                (category,),
            )
            rows = cur.fetchall()
        return [{"id": r[0], "content": r[1], "category": r[2], "importance": float(r[3]),
                 "source": r[4], "created_at": r[5]} for r in rows]

    # ── update / delete ──────────────────────────────────────────────────────
    def update(self, memory_id, content: str | None = None, importance: float | None = None,
               embedding=None) -> None:
        sets, params = ["updated_at = now()"], []
        if content is not None:
            sets.append("content = %s"); params.append(content)
        if importance is not None:
            sets.append("importance = %s"); params.append(importance)
        if embedding is not None:
            sets.append("embedding = %s::vector"); params.append(_vec_literal(embedding))
        params.append(memory_id)
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = %s", params)

    def soft_delete(self, memory_id) -> None:
        """Mark inactive (superseded_by = self)."""
        with self.conn.cursor() as cur:
            cur.execute("UPDATE memories SET superseded_by = id, updated_at = now() WHERE id = %s",
                        (memory_id,))

    def supersede(self, old_id, new_id) -> None:
        with self.conn.cursor() as cur:
            cur.execute("UPDATE memories SET superseded_by = %s, updated_at = now() WHERE id = %s",
                        (new_id, old_id))

    def hard_delete(self, memory_id) -> None:
        with self.conn.cursor() as cur:
            cur.execute("UPDATE memories SET superseded_by = NULL WHERE superseded_by = %s", (memory_id,))
            cur.execute("DELETE FROM memories WHERE id = %s", (memory_id,))

    def count_active(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM memories WHERE superseded_by IS NULL")
            return int(cur.fetchone()[0])
