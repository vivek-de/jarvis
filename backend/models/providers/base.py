"""
backend/models/providers/base.py — provider abstraction (Phase 1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ModelResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_inr: float = 0.0
    latency_ms: int = 0
    success: bool = True
    error: str | None = None
    extra: dict = field(default_factory=dict)


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(self, messages: list[dict], model: str, **opts) -> ModelResult:
        """messages: [{'role','content'}]. Must never raise for expected failures —
        return ModelResult(success=False, error=...) so the router can react."""
        raise NotImplementedError

    def estimate_cost_inr(self, prompt_tokens: int, completion_tokens: int, usd_inr: float) -> float:
        return 0.0

    async def health(self) -> dict:
        return {"provider": self.name, "ok": True}
