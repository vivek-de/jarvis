"""
backend/memory/service.py — high-level long-term memory service (Phase 3).
Ties the pgvector store + Ollama embeddings + Phase-2 policy + importance scoring
together behind a small API the agent uses. Degrades gracefully: if DATABASE_URL is
unset or Postgres/embeddings are unavailable, the service is DISABLED and every call
is a safe no-op so JARVIS keeps working on SQLite sessions alone.
"""
from __future__ import annotations

from ..logging_setup import get_logger
from .embeddings import EmbeddingError, OllamaEmbeddings
from .importance import score_for
from .policy import should_remember

log = get_logger("jarvis.memory")


class MemoryService:
    def __init__(self, enabled: bool, store=None, embeddings=None, reason: str | None = None):
        self.enabled = enabled
        self.store = store
        self.embeddings = embeddings
        self.reason = reason

    # ── construction with graceful fallback ──────────────────────────────────
    @classmethod
    def create(cls, settings) -> "MemoryService":
        if not settings.database_url:
            return cls(False, reason="JARVIS_DATABASE_URL not set — long-term memory disabled")
        try:
            from .pg import connect, run_migrations
            from .store import MemoryStore
            applied = run_migrations(settings.database_url)
            if applied:
                log.info("memory.migrations", extra={"versions": applied})
            conn = connect(settings.database_url)
            store = MemoryStore(conn, dedupe_threshold=settings.memory_dedupe_threshold)
            emb = OllamaEmbeddings(settings.ollama_base_url, settings.embed_model, settings.embed_dim)
            log.info("memory.enabled", extra={"embed_model": settings.embed_model})
            return cls(True, store=store, embeddings=emb)
        except Exception as e:
            log.warning("memory.disabled", extra={"error": str(e)})
            return cls(False, reason=f"memory init failed: {e}")

    # ── write ────────────────────────────────────────────────────────────────
    async def remember(self, content: str, category: str | None = None,
                       source: str = "user", importance: float | None = None) -> dict | None:
        if not self.enabled:
            return None
        category = (category or "fact").lower()
        try:
            vec = await self.embeddings.embed(content)
            imp = score_for(category, override=importance)
            res = self.store.add(content, category, vec, importance=imp, source=source)
            log.info("memory.stored", extra={"action": res.get("action"), "category": category, "importance": imp})
            return {**res, "category": category, "importance": imp}
        except (EmbeddingError, Exception) as e:  # never break a chat turn on a memory failure
            log.warning("memory.remember_failed", extra={"error": str(e)})
            return None

    async def maybe_remember(self, text: str, source: str = "user") -> dict | None:
        """Apply the Phase-2 policy; store only if it says so."""
        if not self.enabled:
            return None
        decision = should_remember(text, source=source)
        if not decision.remember:
            return None
        return await self.remember(text, category=decision.category, source=source)

    # ── read ─────────────────────────────────────────────────────────────────
    async def recall(self, query: str, top_k: int = 5, min_similarity: float | None = None) -> list[dict]:
        if not self.enabled:
            return []
        try:
            vec = await self.embeddings.embed(query)
            return self.store.search(vec, top_k=top_k, min_similarity=min_similarity)
        except Exception as e:
            log.warning("memory.recall_failed", extra={"error": str(e)})
            return []

    async def retrieve_context(self, query: str, top_k: int = 5, floor: float = 0.35) -> list[dict]:
        """Memories relevant enough to inject into the prompt."""
        return await self.recall(query, top_k=top_k, min_similarity=floor)

    # ── delete ───────────────────────────────────────────────────────────────
    async def forget(self, topic: str, hard: bool = False,
                     top_k: int = 20, min_similarity: float = 0.6) -> int:
        if not self.enabled:
            return 0
        try:
            vec = await self.embeddings.embed(topic)
            matches = self.store.search(vec, top_k=top_k, min_similarity=min_similarity)
            for m in matches:
                self.store.hard_delete(m["id"]) if hard else self.store.soft_delete(m["id"])
            log.info("memory.forgot", extra={"topic": topic, "n": len(matches), "hard": hard})
            return len(matches)
        except Exception as e:
            log.warning("memory.forget_failed", extra={"error": str(e)})
            return 0

    def status(self) -> dict:
        s = {"enabled": self.enabled}
        if not self.enabled:
            s["reason"] = self.reason
        else:
            try:
                s["active_memories"] = self.store.count_active()
            except Exception as e:
                s["error"] = str(e)
        return s
