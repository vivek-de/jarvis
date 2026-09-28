"""
backend/trading/optioniq_client.py — READ-ONLY OptionIQ client (Phase 4 groundwork).
═══════════════════════════════════════════════════════════════════════════════
GETs data from the local OptionIQ backend (:3001). SSRF-guarded (only the allowlisted
host:port is permitted). It exposes NO write/order methods — JARVIS never places,
approves, or executes trades. Every call degrades gracefully if OptionIQ is down.
"""
from __future__ import annotations

import httpx

from ..security.ssrf import check_url, SSRFError


class OptionIQClient:
    def __init__(self, base_url: str, allowlist: set[str], timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.allowlist = allowlist
        self.timeout = timeout

    async def get(self, path: str) -> dict:
        """GET {base}{path} → {ok, data} or {ok:False, error}. Read-only, SSRF-checked."""
        url = self.base_url + path
        try:
            check_url(url, self.allowlist)          # SSRF: only allowlisted host:port
        except SSRFError as e:
            return {"ok": False, "error": f"blocked: {e}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return {"ok": False, "error": f"OptionIQ HTTP {r.status_code}", "status": r.status_code}
            return {"ok": True, "data": r.json()}
        except Exception as e:
            return {"ok": False, "error": f"OptionIQ unreachable: {e}"}
