"""
backend/mcp/registry.py — discover external MCP servers and expose their tools (Phase 6).
═══════════════════════════════════════════════════════════════════════════════
On startup, for each ENABLED server in mcp/servers.json:
  1. start the client (bounded by a per-server timeout so a hang can't freeze boot),
  2. list its tools,
  3. wrap each as an MCPTool (a BaseTool) named "<server>.<tool>" and register it in
     the shared ToolRegistry — inheriting the server's permission tier (never above it).

A server that is disabled, times out, or fails is recorded in get_server_status()
with its error and simply skipped. JARVIS keeps running with whatever succeeded.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..logging_setup import get_logger
from ..tools.base import BaseTool, ToolPermission, ToolRegistry, ToolResult
from .client import MCPServerClient

log = get_logger("jarvis.mcp")
# backend/mcp/registry.py → parents[2] = project root
ROOT = Path(__file__).resolve().parents[2]


class MCPTool(BaseTool):
    """Wraps one remote MCP tool as a BaseTool. Registered for discovery/audit; it is
    invoked through the async execute() path (MCP calls are async), so _run() only
    returns a clear directive if something calls it synchronously by mistake."""

    def __init__(self, client: MCPServerClient, remote_name: str, description: str,
                 input_schema: dict, permission: ToolPermission):
        self.name = f"{client.name}.{remote_name}"
        self.description = description
        self.permission = permission
        self.schema = input_schema or {}
        self._client = client
        self._remote_name = remote_name

    def _run(self, args: dict) -> ToolResult:
        return ToolResult.fail(f"{self.name} is an MCP tool — invoke via async execute()")

    async def execute(self, args: dict | None = None) -> ToolResult:
        args = args or {}
        # Same FINANCIAL gate as BaseTool.run(): never executed without confirm=True.
        if self.permission is ToolPermission.FINANCIAL and args.get("confirm") is not True:
            return ToolResult.fail(
                f"FINANCIAL MCP tool {self.name} refused: requires explicit confirm=True.")
        return await self._client.call_tool(self._remote_name, args)


class MCPRegistry:
    def __init__(self):
        self.clients: list[MCPServerClient] = []
        self._status: dict[str, dict] = {}

    @staticmethod
    def load_config(path: str | Path = "mcp/servers.json") -> list[dict]:
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            log.warning("mcp.config_missing", extra={"path": str(p)})
            return []
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("mcp.config_bad_json", extra={"path": str(p), "error": str(e)})
            return []
        servers = raw.get("servers", raw) if isinstance(raw, dict) else raw
        return servers if isinstance(servers, list) else []

    async def startup(self, tool_registry: ToolRegistry,
                      config_path: str | Path = "mcp/servers.json",
                      timeout_s: float = 20.0) -> None:
        for cfg in self.load_config(config_path):
            name = cfg.get("name", "<unnamed>")
            if not cfg.get("enabled", True):
                self._status[name] = {"enabled": False, "tool_count": 0, "error": None}
                log.info("mcp.skipped_disabled", extra={"server": name})
                continue

            client = MCPServerClient(cfg)
            try:
                ok = await asyncio.wait_for(client.start(), timeout=timeout_s)
            except asyncio.TimeoutError:
                await client.stop()
                self._status[name] = {"enabled": True, "tool_count": 0,
                                      "error": f"start timed out after {timeout_s}s"}
                log.warning("mcp.start_timeout", extra={"server": name})
                continue

            if not ok:
                self._status[name] = {"enabled": True, "tool_count": 0, "error": client.error}
                continue

            self.clients.append(client)
            count = 0
            try:
                for t in await client.list_tools():
                    tool = MCPTool(client, t["name"], t["description"],
                                   t["inputSchema"], client.permission)
                    try:
                        tool_registry.register(tool)
                        count += 1
                    except ValueError:  # duplicate name — keep the first, note it
                        log.warning("mcp.duplicate_tool", extra={"tool": tool.name})
                self._status[name] = {"enabled": True, "tool_count": count, "error": None}
                log.info("mcp.tools_registered", extra={"server": name, "count": count})
            except Exception as e:
                self._status[name] = {"enabled": True, "tool_count": count, "error": str(e)}
                log.warning("mcp.list_tools_failed", extra={"server": name, "error": str(e)})

    async def shutdown(self) -> None:
        for c in self.clients:
            await c.stop()
        self.clients = []

    def get_server_status(self) -> dict:
        return self._status
