"""
backend/api/trading.py — read-only trading intelligence API (Phase 13), mounted at /trading.
  GET  /trading/health          → {optioniq: bool, jarvis: "ok"}
  GET  /trading/chain/{symbol}   → {summary, chain: raw strike table}
  GET  /trading/snapshot/{symbol}→ {snapshot}
  POST /trading/query            → {query, symbol} → grounded analyst answer
  GET  /trading/pcr/{symbol}     → {pcr, bias}

Read-only by construction. A hard guard blocks any write method (PUT/PATCH/DELETE) to
/trading/* — it logs CRITICAL and returns 403. There is no order-entry path anywhere.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..logging_setup import get_logger
from ..trading.intelligence import pcr_bias

router = APIRouter(prefix="/trading", tags=["trading"])
log = get_logger("jarvis.api.trading")


class QueryIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    symbol: str = Field("NIFTY", min_length=1, max_length=40)


def _svc(request: Request):
    client = getattr(request.app.state, "trading_client", None)
    intel = getattr(request.app.state, "trading_intel", None)
    if client is None or intel is None:
        raise HTTPException(status_code=503, detail="trading intelligence disabled (JARVIS_TRADING_ENABLED=false)")
    return client, intel


# ── hard write-block: any mutating verb on /trading/* is refused + logged CRITICAL ──
@router.api_route("/{path:path}", methods=["PUT", "PATCH", "DELETE"])
async def _block_writes(path: str, request: Request):
    log.critical("trading.write_blocked", extra={"method": request.method, "path": f"/trading/{path}"})
    raise HTTPException(status_code=403, detail="trading API is strictly read-only")


@router.get("/health")
async def health(request: Request):
    client, _ = _svc(request)
    return {"optioniq": await client.healthcheck(), "jarvis": "ok"}


@router.get("/chain/{symbol}")
async def chain(symbol: str, request: Request, expiry: str | None = None):
    client, intel = _svc(request)
    summary = await intel.chain_summary(symbol, expiry)
    raw = await client.get_chain(symbol, expiry)
    return {"symbol": symbol, "summary": summary,
            "chain": (raw.get("chain") if isinstance(raw, dict) and "error" not in raw else []),
            "spot": (raw.get("spot") if isinstance(raw, dict) else None)}


@router.get("/snapshot/{symbol}")
async def snapshot(symbol: str, request: Request):
    _, intel = _svc(request)
    return {"symbol": symbol, "snapshot": await intel.market_snapshot(symbol)}


@router.post("/query")
async def query(body: QueryIn, request: Request):
    _, intel = _svc(request)
    answer = await intel.answer_query(body.query, body.symbol)
    return {"symbol": body.symbol, "query": body.query, "answer": answer}


@router.get("/pcr/{symbol}")
async def pcr(symbol: str, request: Request):
    client, _ = _svc(request)
    res = await client.get_pcr(symbol)
    if "error" in res:
        raise HTTPException(status_code=502, detail=res["error"])
    return {"symbol": symbol, "pcr": res.get("pcr"), "bias": pcr_bias(res.get("pcr"))}
