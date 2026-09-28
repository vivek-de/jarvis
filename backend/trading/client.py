"""
backend/trading/client.py — READ-ONLY OptionIQ HTTP client (Phase 13).
═══════════════════════════════════════════════════════════════════════════════
Async GETs against the local OptionIQ backend (:3001). Every method is read-only,
SSRF-guarded to the local OptionIQ host, times out at 10s, and NEVER raises — it
returns {"error": ...} on any failure so callers degrade gracefully. There are no
write/order methods here: JARVIS never places, approves, or executes trades.

Real OptionIQ endpoints used:
  GET /api/health
  GET /api/option-chain/{symbol}?expiry=   → {spot, atm, expiry, expiries, pcr, chain[]}
  GET /api/oi/{symbol}                     → {maxPain, resistance, support, ...}
  GET /api/iv/{symbol}                     → {atmIV, ivPercentile, skew[]}
"""
from __future__ import annotations

import httpx

from ..security.ssrf import SSRFError, check_url

DEFAULT_ALLOWLIST = {"localhost:3001", "127.0.0.1:3001"}


class OptionIQClient:
    base = "http://localhost:3001"

    def __init__(self, base: str | None = None, allowlist: set[str] | None = None,
                 timeout: float = 10.0, transport=None):
        self.base = (base or self.base).rstrip("/")
        self.allowlist = allowlist or set(DEFAULT_ALLOWLIST)
        self.timeout = timeout
        self._transport = transport          # httpx.MockTransport in tests; None in prod

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base + path
        try:
            check_url(url, self.allowlist)    # SSRF: local OptionIQ host only
        except SSRFError as e:
            return {"error": f"blocked: {e}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
                r = await c.get(url, params={k: v for k, v in (params or {}).items() if v is not None})
            if r.status_code != 200:
                return {"error": f"OptionIQ HTTP {r.status_code}"}
            return r.json()
        except Exception as e:               # network/parse errors → graceful
            return {"error": f"OptionIQ unreachable: {e}"}

    async def get_chain(self, symbol: str, expiry: str | None = None) -> dict:
        return await self._get(f"/api/option-chain/{symbol}", {"expiry": expiry})

    async def get_pcr(self, symbol: str) -> dict:
        d = await self.get_chain(symbol)
        if "error" in d:
            return d
        pcr = d.get("pcr")
        try:
            pcr = float(pcr)
        except (TypeError, ValueError):
            pcr = None
        return {"pcr": pcr, "spot": d.get("spot")}

    async def get_oi_buildup(self, symbol: str) -> dict:
        return await self._get(f"/api/oi/{symbol}")

    async def get_iv(self, symbol: str) -> dict:
        return await self._get(f"/api/iv/{symbol}")

    async def get_underlying(self, symbol: str) -> dict:
        d = await self.get_chain(symbol)
        if "error" in d:
            return d
        return {"spot": d.get("spot"), "atm": d.get("atm"), "expiry": d.get("expiry")}

    async def healthcheck(self) -> bool:
        d = await self._get("/api/health")
        return isinstance(d, dict) and "error" not in d
