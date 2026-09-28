"""Phase 9 — scheduler: store CRUD, due query, next_run calc, reminders, NL parse, engine.

SQLite runs in-memory; the async engine is driven with a single tick() (no real loop);
croniter is optional (cron next_run test is importorskip'd).
"""
import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest

from backend.scheduler.engine import SchedulerEngine
from backend.scheduler.nlp import parse_schedule
from backend.scheduler.reminders import ReminderStore
from backend.scheduler.store import TaskStore
from backend.scheduler.triggers import IST, compute_next_run, now_ist, parse_dt


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


# ══ store CRUD ════════════════════════════════════════════════════════════════
def test_create_and_get_task(conn):
    s = TaskStore(conn)
    t = s.create_task("check", "interval", "3600", "remind", action_payload={"message": "hi"})
    assert t["id"] and t["enabled"] is True and t["action_payload"] == {"message": "hi"}
    assert s.get_task(t["id"])["name"] == "check"


def test_list_tasks(conn):
    s = TaskStore(conn)
    s.create_task("a", "interval", "3600", "remind")
    s.create_task("b", "interval", "3600", "remind")
    assert len(s.list_tasks()) == 2


def test_get_missing_returns_none(conn):
    assert TaskStore(conn).get_task("nope") is None


def test_delete_task(conn):
    s = TaskStore(conn)
    t = s.create_task("a", "interval", "3600", "remind")
    assert s.delete_task(t["id"]) == 1 and s.get_task(t["id"]) is None
    assert s.delete_task("nope") == 0


def test_update_disable(conn):
    s = TaskStore(conn)
    t = s.create_task("a", "interval", "3600", "remind")
    assert s.update_task(t["id"], enabled=False)["enabled"] is False


def test_update_trigger_recomputes_next_run(conn):
    s = TaskStore(conn)
    t = s.create_task("a", "interval", "3600", "remind")
    old = t["next_run"]
    u = s.update_task(t["id"], trigger_value="60")
    assert u["next_run"] is not None and u["next_run"] < old   # 60s < 3600s away


def test_get_due_tasks(conn):
    s = TaskStore(conn)
    past = (now_ist() - timedelta(minutes=5)).isoformat()
    future = (now_ist() + timedelta(hours=1)).isoformat()
    due = s.create_task("due", "interval", "3600", "remind", next_run=past)
    notdue = s.create_task("later", "interval", "3600", "remind", next_run=future)
    ids = {t["id"] for t in s.get_due_tasks(now_ist().isoformat())}
    assert due["id"] in ids and notdue["id"] not in ids


# ══ triggers ══════════════════════════════════════════════════════════════════
def test_compute_next_run_interval():
    base = datetime(2026, 1, 1, 8, 0, tzinfo=IST)
    assert compute_next_run("interval", "60", after=base).startswith("2026-01-01T08:01:00")


def test_compute_next_run_once_future_and_past():
    base = now_ist()
    fut = (base + timedelta(hours=2)).isoformat()
    assert compute_next_run("once", fut, after=base) is not None
    past = (base - timedelta(hours=2)).isoformat()
    assert compute_next_run("once", past, after=base) is None


def test_compute_next_run_cron():
    pytest.importorskip("croniter")
    base = datetime(2026, 1, 1, 8, 0, tzinfo=IST)
    nxt = compute_next_run("cron", "0 9 * * *", after=base)
    assert nxt.startswith("2026-01-01T09:00:00")


# ══ reminders ═════════════════════════════════════════════════════════════════
def test_reminder_add_pending_deliver(conn):
    r = ReminderStore(conn)
    past = (now_ist() - timedelta(minutes=1)).isoformat()
    rid = r.add_reminder("ping", scheduled_for=past)
    pending = r.get_pending_reminders()
    assert len(pending) == 1 and pending[0]["message"] == "ping"
    assert r.mark_delivered(rid) == 1
    assert r.get_pending_reminders() == []


def test_reminder_future_not_pending(conn):
    r = ReminderStore(conn)
    r.add_reminder("later", scheduled_for=(now_ist() + timedelta(hours=1)).isoformat())
    assert r.get_pending_reminders() == []


# ══ NL parse ══════════════════════════════════════════════════════════════════
def test_parse_cron_every_day():
    s = parse_schedule("remind me at 9am every day to check markets")
    assert s["trigger_type"] == "cron" and s["trigger_value"] == "0 9 * * *"
    assert s["action_type"] == "remind" and s["action_payload"]["message"] == "check markets"


def test_parse_relative_once():
    s = parse_schedule("remind me in 30 minutes to call Roshan")
    assert s["trigger_type"] == "once" and s["action_payload"]["message"] == "call Roshan"
    assert parse_dt(s["trigger_value"]) > now_ist()


def test_parse_every_morning_message():
    s = parse_schedule("every morning give me my schedule")
    assert s["trigger_type"] == "cron" and s["trigger_value"] == "0 9 * * 1-5"
    assert s["action_type"] == "message" and "schedule" in s["action_payload"]["message"]


def test_parse_gibberish_returns_none():
    assert parse_schedule("what's the weather like today") is None


# ══ engine ════════════════════════════════════════════════════════════════════
def test_engine_executes_remind(conn):
    tasks, rem = TaskStore(conn), ReminderStore(conn)
    eng = SchedulerEngine(tasks, rem, agent=None)
    past = (now_ist() - timedelta(minutes=1)).isoformat()
    t = tasks.create_task("r", "once", past, "remind",
                          action_payload={"message": "check markets"}, next_run=past)
    assert asyncio.run(eng.tick()) == 1
    assert any(p["message"] == "check markets" for p in rem.get_pending_reminders())
    after = tasks.get_task(t["id"])
    assert after["last_run"] is not None and after["next_run"] is None    # one-shot done


def test_engine_message_uses_agent(conn):
    tasks, rem = TaskStore(conn), ReminderStore(conn)

    class FakeAgent:
        async def chat(self, message, channel=None):
            return {"reply": f"schedule for {message}"}

    eng = SchedulerEngine(tasks, rem, agent=FakeAgent())
    past = (now_ist() - timedelta(minutes=1)).isoformat()
    tasks.create_task("m", "once", past, "message",
                      action_payload={"message": "what's my schedule"}, next_run=past)
    asyncio.run(eng.tick())
    assert any("schedule for what's my schedule" in p["message"] for p in rem.get_pending_reminders())


# ══ API endpoints ═════════════════════════════════════════════════════════════
@pytest.fixture
def sched_client(settings, stub_ollama):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    with TestClient(create_app(settings)) as c:      # scheduler_enabled=False in test settings
        yield c


def test_api_create_and_list(sched_client):
    r = sched_client.post("/tasks", json={"name": "t", "trigger_type": "interval",
                                          "trigger_value": "3600", "action_type": "remind",
                                          "action_payload": {"message": "hi"}})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert any(t["id"] == tid for t in sched_client.get("/tasks").json()["tasks"])


def test_api_get_patch_delete(sched_client):
    tid = sched_client.post("/tasks", json={"name": "t", "trigger_type": "interval",
                                            "trigger_value": "3600", "action_type": "remind"}).json()["id"]
    assert sched_client.get(f"/tasks/{tid}").status_code == 200
    assert sched_client.patch(f"/tasks/{tid}", json={"enabled": False}).json()["enabled"] is False
    assert sched_client.delete(f"/tasks/{tid}").status_code == 200
    assert sched_client.get(f"/tasks/{tid}").status_code == 404


def test_api_invalid_trigger_and_action(sched_client):
    assert sched_client.post("/tasks", json={"name": "t", "trigger_type": "bogus",
                                             "trigger_value": "x", "action_type": "remind"}).status_code == 400
    assert sched_client.post("/tasks", json={"name": "t", "trigger_type": "interval",
                                             "trigger_value": "3600", "action_type": "trade"}).status_code == 400


def test_api_reminders_pending_marks_delivered(sched_client):
    store = sched_client.app.state.reminders
    store.add_reminder("ping", scheduled_for=(now_ist() - timedelta(minutes=1)).isoformat())
    r = sched_client.get("/reminders/pending")
    assert r.status_code == 200 and r.json()["count"] >= 1
    assert all(x["message"] != "ping" for x in sched_client.get("/reminders/pending").json()["reminders"])
