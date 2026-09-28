"""
backend/trading/intelligence.py — summarise OptionIQ data into grounded text (Phase 13).
═══════════════════════════════════════════════════════════════════════════════
Turns raw OptionIQ JSON into LLM-ready snippets and answers questions strictly from
that data. No fabrication: if a number isn't in the data it's reported as n/a. The
analyst persona is read-only — it never suggests, recommends, or implies trades.

answer_query calls a `generate(messages) -> str` coroutine (injected; defaults to a
local Ollama call), so it's testable offline and never reaches a broker.
"""
from __future__ import annotations

from ..logging_setup import get_logger

log = get_logger("jarvis.trading")

ANALYST_SYSTEM = (
    "You are a read-only market analyst. Answer ONLY from the data provided below. "
    "Never suggest, recommend, or imply trades or positions. Never invent prices, "
    "strikes, OI, or IV numbers — if the data doesn't contain the answer, say so plainly."
)


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def pcr_bias(pcr) -> str:
    """Heuristic label for a put-call ratio (contrarian read; not advice)."""
    try:
        p = float(pcr)
    except (TypeError, ValueError):
        return "n/a"
    if p >= 1.3:
        return "bullish tilt (heavy put OI = support)"
    if p <= 0.7:
        return "bearish tilt (heavy call OI = resistance)"
    return "neutral"


class TradingIntelligence:
    def __init__(self, client, generate=None, model: str = "llama3.2",
                 ollama_base: str = "http://localhost:11434"):
        self.client = client
        self.model = model
        self.ollama_base = ollama_base.rstrip("/")
        self._generate = generate or self._default_generate

    async def chain_summary(self, symbol: str, expiry: str | None = None) -> str:
        d = await self.client.get_chain(symbol, expiry)
        if "error" in d:
            return f"Live option-chain data for {symbol} is unavailable ({d['error']})."
        chain = d.get("chain") or []
        if not chain:
            return f"No option-chain rows returned for {symbol}."
        ce = sorted(chain, key=lambda r: _num(r.get("CE", {}).get("oi")), reverse=True)[:5]
        pe = sorted(chain, key=lambda r: _num(r.get("PE", {}).get("oi")), reverse=True)[:5]
        oi = await self.client.get_oi_buildup(symbol)
        maxpain = oi.get("maxPain") if isinstance(oi, dict) and "error" not in oi else None

        def _row(r, side):
            return f"{r.get('strike')} (OI {int(_num(r.get(side, {}).get('oi')))})"

        lines = [
            f"{symbol} option chain — expiry {d.get('expiry', '?')}, spot {d.get('spot', '?')}:",
            "Top CE by OI: " + ", ".join(_row(r, "CE") for r in ce),
            "Top PE by OI: " + ", ".join(_row(r, "PE") for r in pe),
            f"PCR: {d.get('pcr', 'n/a')}",
            f"Max-pain strike: {maxpain if maxpain is not None else 'n/a'}",
        ]
        return "\n".join(lines)

    async def market_snapshot(self, symbol: str) -> str:
        d = await self.client.get_chain(symbol)
        if "error" in d:
            return f"{symbol}: live data unavailable ({d['error']})."
        iv = await self.client.get_iv(symbol)
        atm_iv = iv.get("atmIV") if isinstance(iv, dict) and "error" not in iv else None
        pcr = d.get("pcr")
        return (
            f"{symbol} snapshot:\n"
            f"Spot: {d.get('spot', 'n/a')}\n"
            f"ATM IV: {atm_iv if atm_iv is not None else 'n/a'}\n"
            f"PCR: {pcr if pcr is not None else 'n/a'} → {pcr_bias(pcr)}\n"
            f"(Read-only from OptionIQ · not trading advice.)"
        )

    async def answer_query(self, query: str, symbol: str) -> str:
        snapshot = await self.market_snapshot(symbol)
        chain = await self.chain_summary(symbol)
        context = f"{snapshot}\n\n{chain}"
        messages = [
            {"role": "system", "content": ANALYST_SYSTEM},
            {"role": "user", "content": f"Data for {symbol}:\n{context}\n\nQuestion: {query}"},
        ]
        try:
            out = (await self._generate(messages) or "").strip()
        except Exception as e:
            log.warning("trading.generate_failed", extra={"error": str(e)})
            out = ""
        return out or f"(model unavailable — here is the live data)\n{context}"

    async def _default_generate(self, messages) -> str:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.ollama_base}/api/chat",
                                 json={"model": self.model, "messages": messages, "stream": False})
            if r.status_code != 200:
                return ""
            return (r.json().get("message") or {}).get("content", "")
        except Exception:
            return ""
