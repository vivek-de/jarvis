"""
backend/models/routing_core.py — pure routing decision logic (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
No third-party imports, so the safety-critical fallback logic (key-gate + spend
cap) can be unit-tested in complete isolation. `router.py` composes this with the
real providers and the SpendTracker.
"""
from __future__ import annotations

from dataclasses import dataclass

CLOUD = {"anthropic", "openai", "gemini"}
KNOWN_PROVIDERS = CLOUD | {"ollama"}


def parse_slot(slot_value: str) -> tuple[str, str]:
    """'anthropic:claude-x' -> ('anthropic','claude-x'); 'ollama:llama3.1:8b' ->
    ('ollama','llama3.1:8b'); a BARE ollama model like 'llama3.1:8b' (note it
    contains a colon) -> ('ollama','llama3.1:8b'). We only treat the text before
    the first ':' as a provider when it is a KNOWN provider name."""
    if ":" in slot_value:
        head, rest = slot_value.split(":", 1)
        if head.strip().lower() in KNOWN_PROVIDERS:
            return head.strip().lower(), rest.strip()
    return "ollama", slot_value.strip()


@dataclass
class RouteDecision:
    task_slot: str
    provider: str
    model: str
    requested_provider: str
    requested_model: str
    is_fallback: bool
    notice: str | None


def route_decision(task_slot: str, slot_value: str, local_model: str,
                   has_key: bool, under_cap: bool) -> RouteDecision:
    """Decide the concrete provider for a task slot.
    Cloud requires BOTH an API key and remaining daily budget; otherwise fall back
    to local Ollama. Local is always allowed and free."""
    provider, model = parse_slot(slot_value)

    if provider not in CLOUD:
        return RouteDecision(task_slot, "ollama", model, provider, model, False, None)
    if not has_key:
        return RouteDecision(task_slot, "ollama", local_model, provider, model, True,
                             f"No API key for '{provider}' — using local {local_model}.")
    if not under_cap:
        return RouteDecision(task_slot, "ollama", local_model, provider, model, True,
                             f"Daily spend cap reached — using local {local_model} instead of {provider}.")
    return RouteDecision(task_slot, provider, model, provider, model, False, None)
