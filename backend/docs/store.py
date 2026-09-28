"""
backend/docs/store.py — pgvector-backed document store (Phase 8).
═══════════════════════════════════════════════════════════════════════════════
Mirrors the memory store: embeddings bound via an explicit `%s::vector` cast (adapter-
independent), cosine distance `<=>`, HNSW index. Shares the memory database and its
migration runner (003_documents.sql lives in memory/migrations).

Graceful degradation is required:
  • No JARVIS_DATABASE_URL / psycopg missing / Postgres down → DocStore.create returns
    None; the API reports the feature is disabled instead of crashing.
  • Embedding a chunk fails → the chunk is stored WITHOUT an embedding (logged), so an
    upload never fails wholesale over one bad chunk. Un-embedded chunks are simply not
    returned by semantic search.
Dedup: a file whose SHA-256 already exists is skipped (no re-embed, no duplicate rows).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from ..logging_setup import get_logger

log = get_logger("jarvis.docs")

EMBED_BATCH = 10


def _vec_literal(embedding) -> str:
    return "[" + ",".join(format(float(x), ".8g") for x in embedding) + "]"


class DocStore:
    def __init__(self, conn, embeddings):
        self.conn = conn
        self.embeddings = embeddings

    @classmethod
    def create(cls, settings) -> "DocStore | None":
        if not settings.database_url:
            log.info("docs.disabled", extra={"reason": "no JARVIS_DATABASE_URL"})
            return None
        try:
            from ..memory.embeddings import OllamaEmbeddings
            from ..memory.pg import connect, run_migrations
            applied = run_migrations(settings.database_url)      # idempotent; includes 003
            if applied:
                log.info("docs.migrations", extra={"versions": applied})
            conn = connect(settings.database_url)
            emb = OllamaEmbeddings(settings.ollama_base_url, settings.embed_model, settings.embed_dim)
            log.info("docs.enabled", extra={"embed_model": settings.embed_model})
            return cls(conn, emb)
        except Exception as e:
            log.warning("docs.init_failed", extra={"error": str(e)})
            return None

    # ── embedding helpers ─────────────────────────────────────────────────────
    async def _safe_embed(self, text: str):
        try:
            return await self.embeddings.embed(text)
        except Exception as e:
            log.warning("docs.embed_failed", extra={"error": str(e)})
            return None

    async def _embed_all(self, texts: list[str]) -> list:
        vecs: list = []
        for i in range(0, len(texts), EMBED_BATCH):
            group = texts[i:i + EMBED_BATCH]
            vecs.extend(await asyncio.gather(*[self._safe_embed(t) for t in group]))
        return vecs

    # ── create ─────────────────────────────────────────────────────────────────
    async def add_document(self, filename: str, chunks: list[dict],
                           file_hash: str | None = None, doc_type: str | None = None) -> dict:
        if file_hash is None:
            from .parser import sha256_bytes
            file_hash = sha256_bytes("".join(c["text"] for c in chunks).encode("utf-8"))
        doc_type = doc_type or (chunks[0]["doc_type"] if chunks else None)

        # dedup on SHA-256
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, chunk_count FROM documents WHERE file_hash = %s", (file_hash,))
            existing = cur.fetchone()
        if existing:
            log.info("docs.dedup_skip", extra={"doc_filename": filename, "doc_id": str(existing[0])})
            return {"ok": True, "skipped": True, "doc_id": existing[0],
                    "chunk_count": int(existing[1]), "embedded": None}

        vecs = await self._embed_all([c["text"] for c in chunks])
        embedded = sum(1 for v in vecs if v is not None)
        doc_id = uuid.uuid4()

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO documents(id, filename, file_hash, doc_type, chunk_count)
                   VALUES (%s,%s,%s,%s,%s)""",
                (doc_id, filename, file_hash, doc_type, len(chunks)),
            )
            for c, vec in zip(chunks, vecs):
                cid = uuid.uuid4()
                if vec is None:
                    cur.execute(
                        """INSERT INTO doc_chunks(id, doc_id, chunk_index, content, embedding, page_ref)
                           VALUES (%s,%s,%s,%s,NULL,%s)""",
                        (cid, doc_id, c["chunk_index"], c["text"], c.get("page_ref")),
                    )
                else:
                    cur.execute(
                        """INSERT INTO doc_chunks(id, doc_id, chunk_index, content, embedding, page_ref)
                           VALUES (%s,%s,%s,%s,%s::vector,%s)""",
                        (cid, doc_id, c["chunk_index"], c["text"], _vec_literal(vec), c.get("page_ref")),
                    )
        log.info("docs.added", extra={"doc_filename": filename, "chunks": len(chunks), "embedded": embedded})
        return {"ok": True, "skipped": False, "doc_id": doc_id,
                "chunk_count": len(chunks), "embedded": embedded}

    # ── read ─────────────────────────────────────────────────────────────────
    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        try:
            qvec = await self.embeddings.embed(query)
        except Exception as e:
            log.warning("docs.query_embed_failed", extra={"error": str(e)})
            return []
        lit = _vec_literal(qvec)
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT c.doc_id, d.filename, c.chunk_index, c.content, c.page_ref,
                          1 - (c.embedding <=> %s::vector) AS similarity
                   FROM doc_chunks c JOIN documents d ON d.id = c.doc_id
                   WHERE c.embedding IS NOT NULL
                   ORDER BY c.embedding <=> %s::vector LIMIT %s""",
                (lit, lit, top_k),
            )
            rows = cur.fetchall()
        return [{"doc_id": r[0], "filename": r[1], "chunk_index": r[2], "content": r[3],
                 "page_ref": r[4], "similarity": float(r[5])} for r in rows]

    def list_documents(self) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT id, filename, uploaded_at, doc_type, chunk_count
                   FROM documents ORDER BY uploaded_at DESC""")
            rows = cur.fetchall()
        return [{"id": str(r[0]), "filename": r[1],
                 "uploaded_at": r[2].isoformat() if r[2] else None,
                 "doc_type": r[3], "chunk_count": int(r[4])} for r in rows]

    def get_document_text(self, doc_id: str, max_chars: int = 12000) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM documents WHERE id = %s", (doc_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                "SELECT content FROM doc_chunks WHERE doc_id = %s ORDER BY chunk_index", (doc_id,))
            parts = [r[0] for r in cur.fetchall()]
        return "\n".join(parts)[:max_chars]

    # ── delete ─────────────────────────────────────────────────────────────────
    def delete_document(self, doc_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))   # cascade → doc_chunks
            return cur.rowcount
