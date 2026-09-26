"""
backend/models/providers/cloud.py — cloud provider classes (Phase 1 = STUBS).
═══════════════════════════════════════════════════════════════════════════════
These are KEY-GATED STUBS. The cost/price tables and estimate_cost_inr() are REAL
(so the spend-cap machinery works and can be tested), but generate() is NOT wired
to the real vendor APIs yet — it returns success=False with a clear STUB message.
Wiring real cloud calls is deliberately deferred; the whole system runs on Ollama
alone. Do not present these as working providers.
"""
from __future__ import annotations

from .base import ModelResult, Provider

# Indicative list prices, USD per 1M tokens (input, output). Used ONLY to estimate
# cost for the daily spend cap; not a billing source of truth.
_PRICES_USD_PER_MTOK = {
    "anthropic": (3.0, 15.0),   # ~Claude Sonnet-class
    "openai": (2.5, 10.0),      # ~GPT-4o-class
    "gemini": (1.25, 5.0),      # ~Gemini Pro-class
}


class _CloudStub(Provider):
    name = "cloud"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def estimate_cost_inr(self, prompt_tokens: int, completion_tokens: int, usd_inr: float) -> float:
        pin, pout = _PRICES_USD_PER_MTOK.get(self.name, (0.0, 0.0))
        usd = (prompt_tokens / 1_000_000) * pin + (completion_tokens / 1_000_000) * pout
        return round(usd * usd_inr, 4)

    async def generate(self, messages: list[dict], model: str | None = None, **opts) -> ModelResult:
        return ModelResult(
            text="", provider=self.name, model=model or "-", success=False,
            error=(f"{self.name} provider is a Phase-1 STUB (not wired to the real API). "
                   f"Point the task slot at 'ollama:...' or implement this provider."),
        )


class AnthropicProvider(_CloudStub):
    name = "anthropic"


class OpenAIProvider(_CloudStub):
    name = "openai"


class GeminiProvider(_CloudStub):
    name = "gemini"
