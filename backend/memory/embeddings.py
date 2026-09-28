"""
backend/memory/embeddings.py — text embeddings via Ollama (Phase 3).
POST {base}/api/embeddings {model, prompt} -> {"embedding": [...]}  (nomic-embed-text = 768-dim).
Async (httpx). Raises EmbeddingError on failure so callers can skip gracefully.
"""
from __future__ import annotations

import httpx


class EmbeddingError(Exception):
    pass


class OllamaEmbeddings:
    def __init__(self, base_url: str, model: str, dim: int = 768, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout = timeout

    async def embed(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            raise EmbeddingError("empty text")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/api/embeddings",
                                      json={"model": self.model, "prompt": text})
        except Exception as e:
            raise EmbeddingError(f"ollama embeddings unreachable: {e}") from e
        if r.status_code != 200:
            raise EmbeddingError(f"ollama embeddings HTTP {r.status_code}: {r.text[:160]}")
        vec = (r.json() or {}).get("embedding")
        if not isinstance(vec, list) or not vec:
            raise EmbeddingError("no embedding in response")
        if self.dim and len(vec) != self.dim:
            raise EmbeddingError(f"embedding dim {len(vec)} != expected {self.dim} "
                                 f"(is JARVIS_EMBED_MODEL='{self.model}' the 768-dim model?)")
        return [float(x) for x in vec]

    async def health(self) -> dict:
        try:
            v = await self.embed("ping")
            return {"ok": True, "model": self.model, "dim": len(v)}
        except Exception as e:
            return {"ok": False, "model": self.model, "error": str(e)}
