"""
backend/api/routes.py — HTTP endpoints (Phase 1).
  GET  /health                — app + DB + Ollama status
  POST /chat                  — one conversation turn
  GET  /conversations/{id}    — message history
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..identity.loader import identity_status
from ..logging_setup import get_logger, request_id_ctx

router = APIRouter()
log = get_logger("jarvis.api")


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    task_slot: str = "GENERAL"
    channel: str = "web"       # web | cli | telegram | voice — controls output formatting


@router.get("/health")
async def health(request: Request):
    app = request.app
    settings = app.state.settings
    db_ok = app.state.db.ping()
    ollama = await app.state.router.health()
    status = "ok" if (db_ok and ollama.get("ok")) else "degraded"
    return {
        "status": status,
        "app": {"name": "jarvis", "version": settings.version, "env": settings.env},
        "db": {"ok": db_ok, "path": str(settings.db_file)},
        "ollama": ollama,
        "identity": identity_status(),
        "memory": app.state.memory.status(),
        "skills": [s["name"] for s in app.state.skills.list_skills()],
        "spend_today_inr": app.state.spend.spent_today(),
        "spend_cap_inr": settings.daily_spend_cap_inr,
    }


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    rid = str(uuid.uuid4())[:8]
    request_id_ctx.set(rid)
    agent = request.app.state.agent
    log.info("chat.request", extra={"task_slot": body.task_slot, "has_session": bool(body.session_id)})
    try:
        out = await agent.chat(body.message, session_id=body.session_id,
                               task_slot=body.task_slot, channel=body.channel)
    except Exception as e:  # never leak a stack trace to the client
        log.exception("chat.error")
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")
    log.info("chat.done", extra={"session_id": out["session_id"],
                                 "provider": out["trace"]["provider"],
                                 "success": out["trace"]["success"],
                                 "latency_ms": out["trace"]["latency_ms"]})
    return out


@router.get("/skills")
async def list_skills(request: Request):
    return {"skills": request.app.state.skills.list_skills()}


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, request: Request):
    db = request.app.state.db
    if not db.conversation_exists(cid):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"session_id": cid, "messages": db.get_messages(cid)}
