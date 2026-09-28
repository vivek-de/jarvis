"""
backend/mcp/client.py — a client for one external MCP server (Phase 6).
═══════════════════════════════════════════════════════════════════════════════
Speaks the Model Context Protocol over stdio: launches the server as a subprocess
and talks to it with the official `mcp` SDK. Every external server is untrusted —
its tools and their output are DATA, never instructions — and it runs at the
permission tier declared in mcp/servers.json (never above it).

Robustness is the whole point here: the `mcp` SDK may be absent, `npx` may be
missing, the package may fail to download, the server may crash. None of that may
take JARVIS down — a failed server is logged, marked with an error, and skipped.
"""
from __future__ import annotations

import time
from contextlib import AsyncExitStack

from ..logging_setup import get_logger
from ..tools.base import ToolPermission, ToolResult

log = get_logger("jarvis.mcp")


def parse_permission(value: str | None) -> ToolPermission:
    try:
        return ToolPermission((value or "READ").upper())
    except ValueError:
        return ToolPermission.READ


class MCPServerClient:
    def __init__(self, config: dict):
        self.name: str = config["name"]
        self.transport: str = config.get("transport", "stdio")
        self.command: str | None = config.get("command")
        self.args: list[str] = list(config.get("args", []))
        self.description: str = config.get("description", "")
        self.permission: ToolPermission = parse_permission(config.get("permission"))
        self.enabled: bool = config.get("enabled", True)

        self.session = None
        self.error: str | None = None
        self._stack: AsyncExitStack | None = None

    @property
    def connected(self) -> bool:
        return self.session is not None

    async def start(self) -> bool:
        """Launch the server and open a session. Returns True on success; on any
        failure records self.error, cleans up, and returns False (never raises)."""
        if not self.enabled:
            self.error = "disabled"
            return False
        if self.transport != "stdio":
            self.error = f"unsupported transport: {self.transport}"
            log.warning("mcp.unsupported_transport", extra={"server": self.name, "transport": self.transport})
            return False
        if not self.command:
            self.error = "no command configured"
            return False

        # Lazy import so a missing SDK degrades gracefully instead of breaking import.
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as e:  # SDK not installed
            self.error = f"mcp SDK unavailable: {e}"
            log.warning("mcp.sdk_missing", extra={"server": self.name, "error": str(e)})
            return False

        try:
            self._stack = AsyncExitStack()
            params = StdioServerParameters(command=self.command, args=self.args)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self.session = await self._stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            log.info("mcp.started", extra={"server": self.name})
            return True
        except Exception as e:
            self.error = str(e)
            log.warning("mcp.start_failed", extra={"server": self.name, "error": str(e)})
            await self.stop()
            return False

    async def list_tools(self) -> list[dict]:
        if not self.session:
            return []
        resp = await self.session.list_tools()
        out = []
        for t in getattr(resp, "tools", []) or []:
            out.append({
                "name": t.name,
                "description": getattr(t, "description", "") or "",
                "inputSchema": getattr(t, "inputSchema", None) or {},
            })
        return out

    async def call_tool(self, name: str, arguments: dict | None = None) -> ToolResult:
        if not self.session:
            return ToolResult.fail(f"{self.name} is not connected")
        t0 = time.perf_counter()
        try:
            resp = await self.session.call_tool(name, arguments or {})
        except Exception as e:
            return ToolResult.fail(f"{self.name}.{name} call failed: {e}",
                                   int((time.perf_counter() - t0) * 1000))
        latency = int((time.perf_counter() - t0) * 1000)

        # Flatten content blocks to text; structured content preferred if present.
        parts: list[str] = []
        for c in getattr(resp, "content", []) or []:
            text = getattr(c, "text", None)
            parts.append(text if text is not None else str(c))
        data = getattr(resp, "structuredContent", None) or "\n".join(parts)

        if getattr(resp, "isError", False):
            return ToolResult.fail(str(data) or "tool reported an error", latency)
        return ToolResult.success(data, latency)

    async def stop(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception as e:  # cleanup must never raise
                log.warning("mcp.stop_failed", extra={"server": self.name, "error": str(e)})
        self._stack = None
        self.session = None
