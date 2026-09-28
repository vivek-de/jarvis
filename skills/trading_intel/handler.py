"""
skills/trading_intel/handler.py — Phase 13 handler.
Routes options-analytics questions to TradingIntelligence.answer_query (read-only).
Detects the symbol from the query (defaults to NIFTY). If OptionIQ is offline, the
answer says the live data is unavailable — it never invents prices.
"""
from __future__ import annotations

import re

_SYMBOLS = ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY", "SENSEX",
            "CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"]


def _detect_symbol(query: str) -> str:
    up = query.upper()
    for s in _SYMBOLS:                       # BANKNIFTY before NIFTY (longest-first order)
        if re.search(rf"\b{s}\b", up):
            return s
    return "NIFTY"


async def handle(ctx, query: str) -> dict:
    settings = getattr(ctx, "settings", None)
    if settings is None or not getattr(settings, "trading_enabled", True):
        return {"reply": "Trading intelligence is disabled.", "sub": "off"}

    from backend.trading.client import OptionIQClient
    from backend.trading.intelligence import TradingIntelligence

    async def _gen(messages):
        if getattr(ctx, "router", None) is None:
            return ""
        result, _ = await ctx.router.generate("GENERAL", messages)
        return result.text if result.success else ""

    base = getattr(settings, "optioniq_base", None) or settings.optioniq_base_url
    client = OptionIQClient(base=base, allowlist=settings.ssrf_allowlist_set)
    intel = TradingIntelligence(client, generate=_gen)

    symbol = _detect_symbol(query)
    answer = await intel.answer_query(query, symbol)
    return {"reply": answer + "\n\nRead-only from OptionIQ · not trading advice.",
            "sub": "query"}
