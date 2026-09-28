"""
backend/agent/runtime.py — conversation loop (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
Minimal but real agent: persists session history in SQLite, routes each turn
through the ModelRouter, records an execution trace (which model/provider, why,
latency, tokens, cost, any fallback), and logs every LLM call. Phase 2 replaces
the built-in system prompt with the identity files; Phase 4/5 add skills/tools.
"""
from __future__ import annotations

from ..database.db import DB
from ..identity.loader import build_system_prompt
from ..models.router import CLOUD, ModelRouter

# The system prompt now comes from the identity files (SOUL.md + USER.md) via the
# loader — the ONLY source of the user's name/details. keep history bounded
# (Phase 3 adds real memory/summarization).
MAX_HISTORY_MESSAGES = 20


class Agent:
    def __init__(self, db: DB, router: ModelRouter, usd_inr_rate: float = 88.0):
        self.db = db
        self.router = router
        self.usd_inr = usd_inr_rate

    async def chat(self, message: str, session_id: str | None = None,
                   task_slot: str = "GENERAL", channel: str = "web") -> dict:
        # 1. resolve/persist session
        if not session_id or not self.db.conversation_exists(session_id):
            session_id = self.db.create_conversation(title=message[:60])
        self.db.add_message(session_id, "user", message)

        # 2. build the prompt: system + bounded history (which now includes this user turn)
        history = self.db.get_messages(session_id, limit=MAX_HISTORY_MESSAGES)
        messages = [{"role": "system", "content": build_system_prompt(channel)}] + \
                   [{"role": m["role"], "content": m["content"]} for m in history]

        # 3. route + generate
        result, decision = await self.router.generate(task_slot, messages)

        # 4. cost accounting (cloud only; local is free)
        cost_inr = 0.0
        if decision.provider in CLOUD and result.success:
            prov = self.router.providers[decision.provider]
            cost_inr = prov.estimate_cost_inr(result.prompt_tokens, result.completion_tokens, self.usd_inr)
        result.cost_inr = cost_inr

        # 5. persist assistant reply only on success; always log the call
        if result.success:
            self.db.add_message(session_id, "assistant", result.text)
        self.db.touch_conversation(session_id)
        self.db.log_llm_call(
            conversation_id=session_id, task_slot=decision.task_slot,
            provider=decision.provider, model=decision.model,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            cost_inr=cost_inr, latency_ms=result.latency_ms,
            success=result.success, error=result.error,
        )

        # 6. execution trace — answers "why did JARVIS do this?"
        trace = {
            "task_slot": decision.task_slot,
            "requested": f"{decision.requested_provider}:{decision.requested_model}",
            "provider": decision.provider,
            "model": decision.model,
            "is_fallback": decision.is_fallback,
            "notice": decision.notice,
            "latency_ms": result.latency_ms,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_inr": cost_inr,
            "success": result.success,
            "error": result.error,
        }

        reply = result.text if result.success else (
            f"⚠️ Model call failed ({decision.provider}): {result.error}"
        )
        return {"session_id": session_id, "reply": reply, "trace": trace}
