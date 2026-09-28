"""
backend/scheduler/engine.py — background scheduler loop (Phase 9).
═══════════════════════════════════════════════════════════════════════════════
A single asyncio task wakes every `poll_seconds` (default 30), asks the TaskStore for
due tasks, executes each, and updates last_run/next_run. Actions:
  • remind  → write a reminder row (picked up via /reminders/pending)
  • message → run the payload through JARVIS (agent.chat) and store the reply as a
              reminder; with no agent, it's queued in-memory instead.

Design guarantees: one task failing never stops the loop or blocks the others; the
agent call is time-boxed; stop() shuts the loop down cleanly on app exit. The scheduler
only ever reads/writes JARVIS's own tables — it never trades or moves money.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress

from ..logging_setup import get_logger
from .reminders import ReminderStore
from .store import TaskStore
from .triggers import compute_next_run, now_ist

log = get_logger("jarvis.scheduler")

AGENT_TIMEOUT_S = 120


class SchedulerEngine:
    def __init__(self, tasks: TaskStore, reminders: ReminderStore, agent=None,
                 poll_seconds: int = 30):
        self.tasks = tasks
        self.reminders = reminders
        self.agent = agent
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.message_queue: list[dict] = []      # used when no agent is wired

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._loop())
            log.info("scheduler.started", extra={"poll_seconds": self.poll_seconds})

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            log.info("scheduler.stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:                      # a bad tick must not kill the loop
                log.exception("scheduler.tick_error")
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)

    async def tick(self) -> int:
        """Run all currently-due tasks. Returns how many were executed."""
        due = self.tasks.get_due_tasks(now_ist().isoformat())
        for task in due:
            await self.execute_task(task)
        return len(due)

    async def execute_task(self, task: dict) -> None:
        now = now_ist().isoformat()
        try:
            await self._run_action(task)
        except Exception as e:                     # isolate per-task failures
            log.warning("scheduler.action_failed",
                        extra={"task_id": task["id"], "error": str(e)})
        try:
            nxt = compute_next_run(task["trigger_type"], task["trigger_value"], after=now_ist())
        except Exception as e:
            log.warning("scheduler.next_run_failed", extra={"task_id": task["id"], "error": str(e)})
            nxt = None
        self.tasks.mark_ran(task["id"], last_run=now, next_run=nxt)

    async def _run_action(self, task: dict) -> None:
        payload = task.get("action_payload") or {}
        message = payload.get("message") or payload.get("text") or task.get("name")
        action = task.get("action_type")
        now = now_ist().isoformat()

        if action == "remind":
            self.reminders.add_reminder(message=message, scheduled_for=now, task_id=task["id"])
            log.info("scheduler.reminded", extra={"task_id": task["id"]})
        elif action == "message":
            if self.agent is not None:
                out = await asyncio.wait_for(
                    self.agent.chat(message, channel="scheduler"), timeout=AGENT_TIMEOUT_S)
                self.reminders.add_reminder(message=out.get("reply", message),
                                            scheduled_for=now, task_id=task["id"])
            else:
                self.message_queue.append({"message": message, "at": now, "task_id": task["id"]})
            log.info("scheduler.messaged", extra={"task_id": task["id"]})
        else:
            raise ValueError(f"unknown action_type: {action!r}")
