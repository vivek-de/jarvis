"""Phase 13 — trading intelligence (READ-ONLY). OptionIQ is mocked via httpx.MockTransport.

Covers the client methods, the text summarisers, a grounded (offline) answer, PCR bias
labels, graceful degradation when OptionIQ is down, skill routing, the /trading endpoints,
and the hard 403 write-block. No live OptionIQ, no broker, no order entry.
"""
import asyncio

import httpx
import pytest

from backend.trading.client import OptionIQClient
from backend.trading.intelligence import TradingIntelligence, pcr_bias

CHAIN = {
    "instrument": "NIFTY", "spot": 24000, "atm": 24000, "expiry": "2026-10-09",
    "expiries": ["2026-10-09"], "pcr": 1.25,
    "chain": [
        {"strike": 23800, "isATM": False, "CE": {"oi": 50, "iv": 13.0}, "PE": {"oi": 900, "iv": 14.0}},
        {"strike": 23900, "isATM": False, "CE": {"oi": 120, "iv": 12.5}, "PE": {"oi": 600, "iv": 13.5}},
        {"strike": 24000, "isATM": True, "CE": {"oi": 300, "iv": 12.0}, "PE": {"oi": 400, "iv": 13.0}},
        {"strike": 24100, "isATM": False, "CE": {"oi": 700, "iv": 11.5}, "PE": {"oi": 150, "iv": 12.5}},
        {"strike": 24200, "isATM": False, "CE": {"oi": 950, "iv": 11.0}, "PE": {"oi": 80, "iv": 12.0}},
    ],
}
OI = {"maxPain": 24000, "resistance": 24200, "support": 23800}
IV = {"atmIV": 12.5, "ivPercentile": 45.0, "skew": []}


def make_client(raise_all=False, health_status=200):
    def handler(request):
        if raise_all:
            raise httpx.ConnectError("connection refused")
        p = request.url.path
        if p == "/api/health":
            return httpx.Response(health_status, json={"status": "ok"})
        if p.startswith("/api/option-chain/"):
            return httpx.Response(200, json=CHAIN)
        if p.startswith("/api/oi/"):
            return httpx.Response(200, json=OI)
        if p.startswith("/api/iv/"):
            return httpx.Response(200, json=IV)
        return httpx.Response(404, json={})
    return OptionIQClient(base="http://localhost:3001", transport=httpx.MockTransport(handler))


def _intel(client=None, gen=None):
    return TradingIntelligence(client or make_client(), generate=gen or (lambda m: _async("")))


async def _async(v):
    return v


# ══ client ════════════════════════════════════════════════════════════════════
def test_healthcheck_true():
    assert asyncio.run(make_client().healthcheck()) is True


def test_healthcheck_false_on_500():
    assert asyncio.run(make_client(health_status=500).healthcheck()) is False


def test_get_chain_ok():
    d = asyncio.run(make_client().get_chain("NIFTY"))
    assert d["spot"] == 24000 and len(d["chain"]) == 5


def test_get_pcr():
    r = asyncio.run(make_client().get_pcr("NIFTY"))
    assert r["pcr"] == 1.25 and r["spot"] == 24000


def test_get_oi_buildup():
    assert asyncio.run(make_client().get_oi_buildup("NIFTY"))["maxPain"] == 24000


def test_get_iv():
    assert asyncio.run(make_client().get_iv("NIFTY"))["atmIV"] == 12.5


def test_get_underlying():
    u = asyncio.run(make_client().get_underlying("NIFTY"))
    assert u["spot"] == 24000 and u["atm"] == 24000


def test_client_error_when_unreachable():
    assert "error" in asyncio.run(make_client(raise_all=True).get_chain("NIFTY"))


def test_client_never_raises_returns_error():
    # a 404 path yields an HTTP error dict, not an exception
    r = asyncio.run(make_client().get_iv("NIFTY"))  # ok
    bad = asyncio.run(make_client(health_status=500).get_chain("NIFTY"))  # chain still 200 here
    assert "error" not in r and isinstance(bad, dict)


# ══ intelligence ══════════════════════════════════════════════════════════════
def test_chain_summary_format():
    s = asyncio.run(_intel().chain_summary("NIFTY"))
    assert "24200" in s and "PCR: 1.25" in s and "Max-pain strike: 24000" in s
    assert "Top CE by OI" in s and "Top PE by OI" in s


def test_market_snapshot_nonempty():
    s = asyncio.run(_intel().market_snapshot("NIFTY"))
    assert "24000" in s and "12.5" in s and "PCR: 1.25" in s and "not trading advice" in s.lower()


def test_answer_query_grounded():
    captured = {}

    async def gen(messages):
        captured["messages"] = messages
        return "Based on the data, PCR is 1.25."

    ans = asyncio.run(TradingIntelligence(make_client(), generate=gen).answer_query("what is the pcr?", "NIFTY"))
    assert "1.25" in ans
    sys = captured["messages"][0]["content"].lower()
    user = captured["messages"][1]["content"]
    assert "read-only" in sys and "never" in sys        # analyst persona, no trades
    assert "24000" in user and "PCR: 1.25" in user       # grounded in real data


def test_answer_query_degrades_when_offline():
    intel = TradingIntelligence(make_client(raise_all=True), generate=lambda m: _async(""))
    ans = asyncio.run(intel.answer_query("pcr?", "NIFTY"))
    assert "unavailable" in ans.lower()                  # no fabrication


def test_pcr_bias_labels():
    assert "bullish" in pcr_bias(1.4)
    assert "bearish" in pcr_bias(0.5)
    assert pcr_bias(1.0) == "neutral"
    assert pcr_bias(None) == "n/a"


def test_chain_summary_offline_message():
    s = asyncio.run(_intel(make_client(raise_all=True)).chain_summary("NIFTY"))
    assert "unavailable" in s.lower()


# ══ skill routing ═════════════════════════════════════════════════════════════
def test_skill_routes_to_trading_intel():
    from backend.skills.registry import SkillRegistry
    reg = SkillRegistry.load()
    assert reg.select("what's the PCR on NIFTY").name == "trading_intel"
    assert reg.select("show me the BANKNIFTY option chain").name == "trading_intel"


def test_skill_routing_preserves_trading_read():
    from backend.skills.registry import SkillRegistry
    reg = SkillRegistry.load()
    assert reg.select("show my portfolio nav and day pnl").name == "trading_read"


# ══ endpoints (fake client/intel injected) ════════════════════════════════════
class FakeClient:
    async def healthcheck(self):
        return True

    async def get_chain(self, s, e=None):
        return CHAIN

    async def get_pcr(self, s):
        return {"pcr": 1.25, "spot": 24000}


class FakeIntel:
    async def chain_summary(self, s, e=None):
        return "CHAIN SUMMARY"

    async def market_snapshot(self, s):
        return "SNAPSHOT"

    async def answer_query(self, q, s):
        return "GROUNDED ANSWER"


@pytest.fixture
def trading_client(settings, stub_ollama):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    with TestClient(create_app(settings)) as c:
        c.app.state.trading_client = FakeClient()
        c.app.state.trading_intel = FakeIntel()
        yield c


def test_endpoint_health(trading_client):
    r = trading_client.get("/trading/health")
    assert r.status_code == 200 and r.json() == {"optioniq": True, "jarvis": "ok"}


def test_endpoint_pcr_with_bias(trading_client):
    r = trading_client.get("/trading/pcr/NIFTY")
    assert r.status_code == 200 and r.json()["pcr"] == 1.25 and "bullish" in r.json()["bias"]


def test_endpoint_chain(trading_client):
    r = trading_client.get("/trading/chain/NIFTY")
    assert r.status_code == 200 and r.json()["summary"] == "CHAIN SUMMARY"
    assert len(r.json()["chain"]) == 5


def test_endpoint_query(trading_client):
    r = trading_client.post("/trading/query", json={"query": "pcr?", "symbol": "NIFTY"})
    assert r.status_code == 200 and r.json()["answer"] == "GROUNDED ANSWER"


def test_endpoint_write_blocked_403(trading_client):
    assert trading_client.delete("/trading/chain/NIFTY").status_code == 403
    assert trading_client.put("/trading/pcr/NIFTY", json={}).status_code == 403
