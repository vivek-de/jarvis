"""
backend/tools/base.py — the tool system core (Phase 5).
═══════════════════════════════════════════════════════════════════════════════
Tools are small, deterministic capabilities the agent can call before the LLM
(read a file, do arithmetic, tell the time). Each tool declares a permission tier
so the runtime knows how much scrutiny a call needs:

  • READ       — safe, side-effect-free. Runs automatically.
  • WRITE      — mutates state. Requires explicit confirmation (enforced in later phases).
  • FINANCIAL  — moves money / places orders. ALWAYS requires confirm=True in args,
                 and JARVIS never actually does this (trading stays read-only) — the
                 gate exists so any such call is refused + audited, never executed.

Nothing here imports pydantic/httpx, so the whole module is unit-testable in a
restricted sandbox.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolPermission(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    FINANCIAL = "FINANCIAL"


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    latency_ms: int = 0

    @classmethod
    def success(cls, data: Any, latency_ms: int = 0) -> "ToolResult":
        return cls(ok=True, data=data, latency_ms=latency_ms)

    @classmethod
    def fail(cls, error: str, latency_ms: int = 0) -> "ToolResult":
        return cls(ok=False, error=error, latency_ms=latency_ms)


class BaseTool(ABC):
    """A capability the agent may invoke. Subclasses set name/description/permission/schema
    and implement _run(args). Call run(args) — it times the call and enforces the
    FINANCIAL confirmation gate before ever reaching _run()."""

    name: str = "base"
    description: str = ""
    permission: ToolPermission = ToolPermission.READ
    schema: dict = {}

    @abstractmethod
    def _run(self, args: dict) -> ToolResult:
        """Do the work. Implementations should be deterministic and side-effect-aware."""
        raise NotImplementedError

    def run(self, args: dict) -> ToolResult:
        args = args or {}
        # FINANCIAL calls are gated: without explicit confirm=True they are refused
        # (never executed). JARVIS is read-only on money, so this stays a hard stop.
        if self.permission is ToolPermission.FINANCIAL and not args.get("confirm") is True:
            return ToolResult.fail(
                "FINANCIAL tool call refused: requires explicit confirm=True "
                "(JARVIS is read-only and never places orders or moves money)."
            )
        t0 = time.perf_counter()
        try:
            res = self._run(args)
        except Exception as e:  # a tool must never crash the agent
            return ToolResult.fail(f"{self.name} raised {type(e).__name__}: {e}",
                                   latency_ms=int((time.perf_counter() - t0) * 1000))
        if res.latency_ms == 0:
            res.latency_ms = int((time.perf_counter() - t0) * 1000)
        return res


@dataclass
class ToolRegistry:
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "permission": t.permission.value, "schema": t.schema}
                for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
