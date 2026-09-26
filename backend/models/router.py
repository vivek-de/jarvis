"""
backend/models/router.py — model router with task slots + spend-cap fallback (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
Task slots (GENERAL/FAST/CODING/REASONING/LOCAL/TRADING) each map to a
"provider:model" string in config. The router resolves a slot to a concrete
provider, applying two guards before allowing a CLOUD call:
  1. key-gate   — no API key for that provider → fall back to LOCAL (Ollama)
  2. spend-cap  — today's cloud spend ≥ ₹cap → fall back to LOCAL
Local (Ollama) is always allowed and free.

`route_decision(...)` is a pure function (stdlib-only) so the safety logic is
unit-testable in isolation; ModelRouter wires it to real providers + SpendTracker.
"""
from __future__ import annotations

from .providers.base import ModelResult
from .providers.cloud import AnthropicProvider, GeminiProvider, OpenAIProvider
from .providers.ollama import OllamaProvider
from .routing_core import CLOUD, RouteDecision, parse_slot, route_decision
from .spend import SpendTracker

__all__ = ["ModelRouter", "RouteDecision", "route_decision", "parse_slot", "CLOUD"]


class ModelRouter:
    def __init__(self, settings, spend_tracker: SpendTracker):
        self.s = settings
        self.spend = spend_tracker
        self.providers = {
            "ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model),
            "anthropic": AnthropicProvider(settings.api_key_for("anthropic")),
            "openai": OpenAIProvider(settings.api_key_for("openai")),
            "gemini": GeminiProvider(settings.api_key_for("gemini")),
        }

    def resolve(self, task_slot: str) -> RouteDecision:
        slots = self.s.task_slots
        slot_value = slots.get(task_slot.upper(), slots["GENERAL"])
        provider, _ = parse_slot(slot_value)
        has_key = bool(self.s.api_key_for(provider)) if provider in CLOUD else True
        return route_decision(
            task_slot=task_slot.upper(),
            slot_value=slot_value,
            local_model=self.s.ollama_model,
            has_key=has_key,
            under_cap=self.spend.under_cap(),
        )

    async def generate(self, task_slot: str, messages: list[dict], **opts) -> tuple[ModelResult, RouteDecision]:
        decision = self.resolve(task_slot)
        provider = self.providers[decision.provider]
        result = await provider.generate(messages, decision.model, **opts)
        return result, decision

    async def health(self) -> dict:
        return await self.providers["ollama"].health()
