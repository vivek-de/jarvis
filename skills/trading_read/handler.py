"""
skills/trading_read/handler.py — read-only OptionIQ queries (UC1/UC7 groundwork).
Maps the question to a READ-ONLY OptionIQ endpoint, formats the result plainly, and
always carries the not-trading-advice caveat. Never places/approves/suggests trades.
"""
from __future__ import annotations

CAVEAT = "Read-only from OptionIQ · not trading advice."


def _inr(x):
    try:
        return "₹" + format(int(round(float(x))), ",")
    except Exception:
        return str(x)


async def handle(ctx, query: str) -> dict:
    return await _run(ctx, query.lower())


async def _run(ctx, low: str) -> dict:
    # build the read-only client lazily (needs httpx + settings)
    from backend.trading.optioniq_client import OptionIQClient  # type: ignore
    s = ctx.settings
    client = OptionIQClient(s.optioniq_base_url, s.ssrf_allowlist_set)

    # ── Kite auth / token ─────────────────────────────────────────────────────
    if "kite" in low or "token" in low or "auth" in low:
        for path in ("/api/auth/status", "/api/kite/status", "/api/health"):
            r = await client.get(path)
            if r["ok"]:
                return {"reply": f"Kite/auth status ({path}): {_short(r['data'])}\n{CAVEAT}", "sub": "kite"}
        return {"reply": "Couldn't read Kite auth status from OptionIQ (is it running and logged in?). "
                         "Login: " + ctx.settings.optioniq_base_url + "/api/auth/login", "sub": "kite"}

    # ── momentum basket ───────────────────────────────────────────────────────
    if "basket" in low or "momentum" in low:
        r = await client.get("/api/momentum/basket")
        if not r["ok"]:
            return {"reply": f"Momentum basket unavailable — {r['error']}.\n{CAVEAT}", "sub": "basket"}
        d = r["data"]
        top = d.get("basket_top20") or d.get("basket") or []
        names = ", ".join(x.get("symbol", "?") for x in top[:5])
        return {"reply": f"Momentum basket (top 5 of {len(top)}): {names}. As of {d.get('as_of','?')}.\n{CAVEAT}",
                "sub": "basket"}

    # ── big player ────────────────────────────────────────────────────────────
    if "big player" in low or "bigplayer" in low:
        r = await client.get("/api/bigplayer/live")
        if not r["ok"]:
            return {"reply": f"Big Player data unavailable — {r['error']}.\n{CAVEAT}", "sub": "bigplayer"}
        return {"reply": f"Big Player (live): {_short(r['data'])}\n{CAVEAT}", "sub": "bigplayer"}

    # ── portfolio / NAV / P&L / journal (default) ────────────────────────────
    r = await client.get("/api/momentum/algo/journal/today")
    if not r["ok"]:
        return {"reply": f"Portfolio journal unavailable — {r['error']}. "
                         f"(Start OptionIQ and log in to Kite.)\n{CAVEAT}", "sub": "journal"}
    d = r["data"]
    nav = _inr(d.get("nav", 0))
    day = d.get("day_pnl", 0); dpct = d.get("day_pnl_pct", 0)
    tot = d.get("total_pnl", 0)
    gainers = ", ".join(g.get("symbol", "?") for g in (d.get("top_gainers") or [])[:3])
    losers = ", ".join(g.get("symbol", "?") for g in (d.get("top_losers") or [])[:3])
    sign = "+" if (day or 0) >= 0 else ""
    reply = (f"Paper portfolio ({d.get('date','today')}): NAV {nav}, "
             f"day P&L {sign}{_inr(day)} ({dpct}%), total P&L {_inr(tot)}.\n"
             f"Top gainers: {gainers or '—'} · losers: {losers or '—'}\n{CAVEAT}")
    return {"reply": reply, "sub": "journal"}


def _short(obj) -> str:
    import json
    s = json.dumps(obj, default=str)
    return s if len(s) <= 300 else s[:300] + "…"
