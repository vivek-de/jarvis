"""Phase 4 — skill loading, dynamic selection/routing, and the placement handler."""
import asyncio

from backend.database.db import DB, run_migrations
from backend.skills.registry import SkillContext, SkillRegistry


def test_registry_loads_priority_skills():
    reg = SkillRegistry.load()
    names = {s.name for s in reg.skills}
    assert {"placement_prep", "project_memory", "trading_read"} <= names
    # every loaded skill has a callable handler + declared permissions
    for s in reg.skills:
        assert callable(s.handler)
        assert "default" in s.permissions


def test_dynamic_selection_routing():
    reg = SkillRegistry.load()
    assert reg.select("solved two-sum topic:arrays").name == "placement_prep"
    assert reg.select("what's due to review today").name == "placement_prep"
    assert reg.select("where did I leave OptionIQ").name == "project_memory"
    assert reg.select("what's pending on RoadSense-AI").name == "project_memory"
    assert reg.select("show my portfolio nav and day pnl").name == "trading_read"
    assert reg.select("is the kite token valid").name == "trading_read"
    assert reg.select("tell me a joke about cats") is None       # no trigger → normal chat


def test_plural_triggers_still_route():
    # regression: "my deadlines" (plural) used to miss the "deadline" trigger and
    # fall through to the LLM, hanging the request.
    reg = SkillRegistry.load()
    assert reg.select("my deadlines").name == "placement_prep"
    assert reg.select("show my open deadlines").name == "placement_prep"


def test_placement_handler_log_due_deadline(tmp_path):
    dbf = tmp_path / "p.db"
    run_migrations(dbf)
    db = DB(dbf)
    skill = SkillRegistry.load().by_name["placement_prep"]
    ctx = SkillContext(db=db, router=None, memory=None, settings=None)

    r = asyncio.run(skill.handler(ctx, "solved two-sum topic:arrays difficulty:easy"))
    assert "two-sum" in r["reply"].lower()
    assert db.dsa_stats()["total"] == 1

    r2 = asyncio.run(skill.handler(ctx, "what's due"))
    assert "review" in r2["reply"].lower()          # nothing due yet (first review tomorrow)

    r3 = asyncio.run(skill.handler(ctx, "deadline Amazon OA on 2026-10-05"))
    assert "2026-10-05" in r3["reply"]
    r4 = asyncio.run(skill.handler(ctx, "my deadlines"))
    assert "Amazon" in r4["reply"]

    r5 = asyncio.run(skill.handler(ctx, "struggled dijkstra topic:graphs"))
    assert "dijkstra" in r5["reply"].lower()
    assert "graphs" in db.dsa_stats()["weak_topics"]
    db.close()


def test_failing_skill_surfaces_error_no_llm_fallthrough(tmp_path):
    # A broken/slow skill must return its real error, never fall through to the model.
    from backend.agent.runtime import Agent
    from backend.skills.registry import Skill, SkillRegistry

    dbf = tmp_path / "a.db"
    run_migrations(dbf)
    db = DB(dbf)

    async def boom(ctx, query):
        raise RuntimeError("kaboom")

    broken = Skill(name="broken", description="", triggers=["deadline"], instructions="",
                   allowed_tools=[], permissions={}, io_schema={}, handler=boom, dir=tmp_path)

    class RouterMustNotRun:
        async def generate(self, *a, **k):
            raise AssertionError("LLM was called — skill error should not fall through")

    agent = Agent(db=db, router=RouterMustNotRun(), memory=None,
                  skills=SkillRegistry([broken]), settings=None)
    out = asyncio.run(agent.chat("my deadlines", channel="cli"))
    assert "kaboom" in out["reply"]
    assert out["trace"]["success"] is False
    db.close()


def test_project_memory_disabled_message():
    skill = SkillRegistry.load().by_name["project_memory"]
    ctx = SkillContext(memory=None)      # memory off
    r = asyncio.run(skill.handler(ctx, "where did I leave OptionIQ"))
    assert "memory" in r["reply"].lower()
