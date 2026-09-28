"""
backend/main.py — FastAPI application factory (Phase 1).
═══════════════════════════════════════════════════════════════════════════════
Wires config → logging → migrations → DB → spend tracker → model router → agent,
mounts the API and the rate-limit middleware. Run with:
    uvicorn backend.main:app --host 127.0.0.1 --port 8100
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .agent.runtime import Agent
from .api.routes import router as api_router
from .config import ROOT, Settings, get_settings
from .database.db import DB, run_migrations
from .logging_setup import get_logger, setup_logging
from .memory.service import MemoryService
from .models.router import ModelRouter
from .models.spend import SpendTracker
from .security.ratelimit import RateLimitMiddleware
from .skills.registry import SkillRegistry


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, ROOT / "logs" / "jarvis.log")
    log = get_logger("jarvis")

    # migrations run at construction so a fresh DB is ready before serving
    applied = run_migrations(settings.db_file)
    if applied:
        log.info("migrations.applied", extra={"versions": applied})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = DB(settings.db_file)
        spend = SpendTracker(db.conn, settings.daily_spend_cap_inr)
        router = ModelRouter(settings, spend)
        memory = MemoryService.create(settings)      # graceful no-op if PG/DATABASE_URL absent
        skills = SkillRegistry.load()
        agent = Agent(db, router, memory=memory, skills=skills, settings=settings,
                      usd_inr_rate=settings.usd_inr_rate, memory_top_k=settings.memory_retrieve_top_k)
        app.state.settings = settings
        app.state.db = db
        app.state.spend = spend
        app.state.router = router
        app.state.memory = memory
        app.state.skills = skills
        app.state.agent = agent
        log.info("startup", extra={
            "memory": memory.status(),
            "skills": [s["name"] for s in skills.list_skills()],
            "version": settings.version,
            "use_cases": settings.use_case_flags(),
            "slots": settings.task_slots,
        })
        try:
            yield
        finally:
            db.close()
            log.info("shutdown")

    app = FastAPI(title="JARVIS", version=settings.version, lifespan=lifespan)
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min)
    app.include_router(api_router)
    return app


app = create_app()
