"""
backend/models/providers/ollama.py — local Ollama provider (Phase 1, WORKING).
═══════════════════════════════════════════════════════════════════════════════
Calls the Ollama HTTP API at {base_url}/api/chat (non-streaming). Local inference
is free, so cost_inr is always 0. If Ollama is down, returns ModelResult(
success=False, error=...) — the caller surfaces a clean message, never a crash.
"""
from __future__ import annotations

import time

import httpx

from .base import ModelResult, Provider


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str, default_model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def generate(self, messages: list[dict], model: str | None = None, **opts) -> ModelResult:
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": opts.get("temperature", 0.4)},
        }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
            latency = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return ModelResult(
                    text="", provider=self.name, model=model, latency_ms=latency,
                    success=False, error=f"ollama HTTP {r.status_code}: {r.text[:200]}",
                )
            data = r.json()
            text = (data.get("message") or {}).get("content", "").strip()
            return ModelResult(
                text=text, provider=self.name, model=model,
                prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
                completion_tokens=int(data.get("eval_count", 0) or 0),
                cost_inr=0.0, latency_ms=latency, success=True,
            )
        except Exception as e:  # connection refused, timeout, etc.
            latency = int((time.perf_counter() - t0) * 1000)
            return ModelResult(
                text="", provider=self.name, model=model, latency_ms=latency,
                success=False, error=f"ollama unreachable: {e}",
            )

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
            if r.status_code == 200:
                models = [m.get("name") for m in r.json().get("models", [])]
                return {"provider": self.name, "ok": True, "models": models}
            return {"provider": self.name, "ok": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"provider": self.name, "ok": False, "error": str(e)}
