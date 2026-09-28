"""
backend/api/scheduler.py — task & reminder HTTP API (Phase 9).
  POST   /tasks               create a scheduled task
  GET    /tasks               list tasks
  GET    /tasks/{id}          get one
  PATCH  /tasks/{id}          enable/disable or change fields
  DELETE /tasks/{id}          delete
  GET    /reminders/pending   undelivered reminders (marks them delivered)

Tasks only ever run JARVIS's own remind/message actions — never a trade or transfer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..scheduler.triggers import validate_trigger

router = APIRouter(tags=["scheduler"])

VALID_ACTIONS = {"remind", "message"}


class TaskIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    trigger_type: str
    trigger_value: str
    action_type: str
    action_payload: dict = Field(default_factory=dict)
    enabled: bool = True


class TaskPatch(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    trigger_value: str | None = None
    action_type: str | None = None
    action_payload: dict | None = None
    enabled: bool | None = None


def _tasks(request: Request):
    store = getattr(request.app.state, "tasks", None)
    if store is None:
        raise HTTPException(status_code=503, detail="scheduler disabled")
    return store


@router.post("/tasks")
async def create_task(body: TaskIn, request: Request):
    if body.action_type not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action_type must be one of {sorted(VALID_ACTIONS)}")
    err = validate_trigger(body.trigger_type, body.trigger_value)
    if err:
        raise HTTPException(status_code=400, detail=err)
    task = _tasks(request).create_task(
        name=body.name, trigger_type=body.trigger_type, trigger_value=body.trigger_value,
        action_type=body.action_type, action_payload=body.action_payload, enabled=body.enabled)
    return task


@router.get("/tasks")
async def list_tasks(request: Request):
    return {"tasks": _tasks(request).list_tasks()}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request):
    task = _tasks(request).get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch, request: Request):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "action_type" in fields and fields["action_type"] not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action_type must be one of {sorted(VALID_ACTIONS)}")
    if "trigger_type" in fields or "trigger_value" in fields:
        cur = _tasks(request).get_task(task_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="task not found")
        err = validate_trigger(fields.get("trigger_type", cur["trigger_type"]),
                               fields.get("trigger_value", cur["trigger_value"]))
        if err:
            raise HTTPException(status_code=400, detail=err)
    task = _tasks(request).update_task(task_id, **fields)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    if _tasks(request).delete_task(task_id) == 0:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "deleted": task_id}


@router.get("/reminders/pending")
async def pending_reminders(request: Request):
    store = getattr(request.app.state, "reminders", None)
    if store is None:
        raise HTTPException(status_code=503, detail="scheduler disabled")
    pending = store.get_pending_reminders()
    for r in pending:
        store.mark_delivered(r["id"])
    return {"reminders": pending, "count": len(pending)}
