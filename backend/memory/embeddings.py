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
                # legacy endpoint first ({prompt} -> {"embedding": [...]})
                r = await client.post(f"{self.base_url}/api/embeddings",
                                      json={"model": self.model, "prompt": text})
                vec = self._extract(r)
                if vec is None:
                    # newer endpoint ({input} -> {"embeddings": [[...]]})
                    r2 = await client.post(f"{self.base_url}/api/embed",
                                           json={"model": self.model, "input": text})
                    vec = self._extract(r2)
                    if vec is None:
                        raise EmbeddingError(
                            f"no embedding from Ollama (HTTP {r.status_code}/{r2.status_code}); "
                            f"is '{self.model}' pulled? try `ollama pull {self.model}`")
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"ollama embeddings unreachable: {e}") from e

        if self.dim and len(vec) != self.dim:
            raise EmbeddingError(f"embedding dim {len(vec)} != expected {self.dim} "
                                 f"(is JARVIS_EMBED_MODEL='{self.model}' the {self.dim}-dim model?)")
        return [float(x) for x in vec]

    @staticmethod
    def _extract(resp) -> list[float] | None:
        """Pull a single embedding vector out of either Ollama response shape."""
        if resp.status_code != 200:
            return None
        try:
            data = resp.json() or {}
        except Exception:
            return None
        v = data.get("embedding")
        if isinstance(v, list) and v:
            return v
        vs = data.get("embeddings")
        if isinstance(vs, list) and vs and isinstance(vs[0], list) and vs[0]:
            return vs[0]
        return None

    async def health(self) -> dict:
        try:
            v = await self.embed("ping")
            return {"ok": True, "model": self.model, "dim": len(v)}
        except Exception as e:
            return {"ok": False, "model": self.model, "error": str(e)}
