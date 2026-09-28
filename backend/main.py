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
from fastapi.middleware.cors import CORSMiddleware

from .agent.runtime import Agent
from .api.docs import router as docs_router
from .api.routes import router as api_router
from .api.scheduler import router as scheduler_router
from .config import ROOT, Settings, get_settings
from .database.db import DB, run_migrations
from .docs.qa import DocQA
from .docs.store import DocStore
from .logging_setup import get_logger, setup_logging
from .mcp.registry import MCPRegistry
from .memory.service import MemoryService
from .models.router import ModelRouter
from .models.spend import SpendTracker
from .scheduler.engine import SchedulerEngine
from .scheduler.reminders import ReminderStore
from .scheduler.store import TaskStore
from .security.ratelimit import RateLimitMiddleware
from .skills.registry import SkillRegistry
from .tools import TOOL_REGISTRY


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

        # MCP: discover external servers and register their tools into TOOL_REGISTRY.
        # Failures are recorded per-server and skipped — they never block startup.
        mcp = MCPRegistry()
        if settings.mcp_enabled:
            try:
                await mcp.startup(TOOL_REGISTRY, settings.mcp_config_path,
                                  timeout_s=settings.mcp_startup_timeout_s)
            except Exception:
                log.exception("mcp.startup_error")

        # Document intelligence (Phase 8): shares the memory DB; None if DB/psycopg absent.
        docs = DocStore.create(settings)

        async def _doc_generate(messages):
            result, _ = await router.generate("GENERAL", messages)
            return result.text if result.success else ""

        docqa = DocQA(_doc_generate)

        agent = Agent(db, router, memory=memory, skills=skills, settings=settings,
                      usd_inr_rate=settings.usd_inr_rate, memory_top_k=settings.memory_retrieve_top_k)

        # Scheduler (Phase 9): SQLite-backed tasks + reminders; background loop optional.
        tasks = TaskStore(db.conn)
        reminders = ReminderStore(db.conn)
        scheduler = SchedulerEngine(tasks, reminders, agent=agent,
                                    poll_seconds=settings.scheduler_poll_seconds)
        if settings.scheduler_enabled:
            await scheduler.start()

        app.state.settings = settings
        app.state.db = db
        app.state.spend = spend
        app.state.router = router
        app.state.memory = memory
        app.state.skills = skills
        app.state.tools = TOOL_REGISTRY
        app.state.mcp = mcp
        app.state.docs = docs
        app.state.docqa = docqa
        app.state.tasks = tasks
        app.state.reminders = reminders
        app.state.scheduler = scheduler
        app.state.agent = agent
        log.info("startup", extra={
            "memory": memory.status(),
            "skills": [s["name"] for s in skills.list_skills()],
            "tools": [t["name"] for t in TOOL_REGISTRY.list_all()],
            "mcp": mcp.get_server_status(),
            "docs": "enabled" if docs is not None else "disabled",
            "scheduler": "on" if settings.scheduler_enabled else "off",
            "version": settings.version,
            "use_cases": settings.use_case_flags(),
            "slots": settings.task_slots,
        })
        try:
            yield
        finally:
            await scheduler.stop()
            await mcp.shutdown()
            db.close()
            log.info("shutdown")

    app = FastAPI(title="JARVIS", version=settings.version, lifespan=lifespan)
    # CORS: allow the local OptionIQ frontend to call the document API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min)
    app.include_router(api_router)
    app.include_router(docs_router)
    app.include_router(scheduler_router)
    return app


app = create_app()
