"""Phase 6 — MCP support: config loading, tool wrapping, graceful failure, endpoints.

Everything here is mocked: no npm/npx subprocess is ever launched. A FakeClient stands
in for MCPServerClient, and load_config is monkeypatched to feed crafted server configs.
"""
import asyncio

from backend.mcp import registry as reg_mod
from backend.mcp.client import parse_permission
from backend.mcp.registry import MCPRegistry, MCPTool
from backend.tools.base import ToolPermission, ToolRegistry, ToolResult


class FakeClient:
    """Drop-in for MCPServerClient. Behaviour is driven by hints in the config dict:
    _start_ok (default True) and _tools (default [])."""

    def __init__(self, config: dict):
        self.name = config["name"]
        self.permission = parse_permission(config.get("permission"))
        self.enabled = config.get("enabled", True)
        self.error = None
        self.stopped = False
        self._start_ok = config.get("_start_ok", True)
        self._tools = config.get("_tools", [])

    async def start(self):
        if not self.enabled:
            self.error = "disabled"
            return False
        if not self._start_ok:
            self.error = "boom"
            return False
        return True

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments=None):
        return ToolResult.success({"tool": name, "echo": arguments})

    async def stop(self):
        self.stopped = True


def _use_fake(monkeypatch, servers):
    monkeypatch.setattr(reg_mod, "MCPServerClient", FakeClient)
    monkeypatch.setattr(MCPRegistry, "load_config", staticmethod(lambda *a, **k: servers))


# ── config loading ────────────────────────────────────────────────────────────
def test_load_config_reads_servers_json():
    servers = MCPRegistry.load_config()      # the real mcp/servers.json
    assert any(s["name"] == "filesystem" for s in servers)
    fs = next(s for s in servers if s["name"] == "filesystem")
    assert fs["permission"] == "READ" and fs["transport"] == "stdio"


def test_load_config_missing_returns_empty(tmp_path):
    assert MCPRegistry.load_config(tmp_path / "nope.json") == []


# ── MCPTool wrapper ─────────────────────────────────────────────────────────────
def test_mcptool_wraps_and_calls():
    fc = FakeClient({"name": "fs", "permission": "READ"})
    tool = MCPTool(fc, "read_file", "reads a file", {"type": "object"}, ToolPermission.READ)
    assert tool.name == "fs.read_file"
    assert tool.permission == ToolPermission.READ
    res = asyncio.run(tool.execute({"path": "x.txt"}))
    assert res.ok and res.data["tool"] == "read_file"
    # a sync call returns a clear directive rather than crashing
    assert tool._run({}).ok is False


def test_mcptool_financial_gate():
    fc = FakeClient({"name": "bank", "permission": "FINANCIAL"})
    tool = MCPTool(fc, "transfer", "", {}, ToolPermission.FINANCIAL)
    assert asyncio.run(tool.execute({})).ok is False               # no confirm → refused
    assert asyncio.run(tool.execute({"confirm": True})).ok is True


# ── startup / discovery / failure handling ──────────────────────────────────────
def test_startup_registers_tools(monkeypatch):
    _use_fake(monkeypatch, [{"name": "fs", "enabled": True, "permission": "READ", "_tools": [
        {"name": "read_file", "description": "r", "inputSchema": {}},
        {"name": "write_file", "description": "w", "inputSchema": {}}]}])
    tr = ToolRegistry()
    r = MCPRegistry()
    asyncio.run(r.startup(tr))
    st = r.get_server_status()["fs"]
    assert st["tool_count"] == 2 and st["error"] is None
    assert tr.get("fs.read_file") is not None
    assert tr.get("fs.read_file").permission == ToolPermission.READ
    asyncio.run(r.shutdown())
    assert r.clients == []


def test_disabled_server_skipped(monkeypatch):
    _use_fake(monkeypatch, [{"name": "off", "enabled": False, "permission": "READ"}])
    tr = ToolRegistry()
    r = MCPRegistry()
    asyncio.run(r.startup(tr))
    assert r.get_server_status()["off"] == {"enabled": False, "tool_count": 0, "error": None}
    assert len(tr) == 0 and r.clients == []


def test_startup_failure_handled_gracefully(monkeypatch):
    _use_fake(monkeypatch, [{"name": "broken", "enabled": True, "permission": "READ",
                             "_start_ok": False}])
    tr = ToolRegistry()
    r = MCPRegistry()
    asyncio.run(r.startup(tr))               # must NOT raise
    st = r.get_server_status()["broken"]
    assert st["error"] == "boom" and st["tool_count"] == 0
    assert len(tr) == 0


# ── endpoints ───────────────────────────────────────────────────────────────────
def test_mcp_status_and_tools_endpoints(client):
    r = client.get("/mcp/status")
    assert r.status_code == 200 and isinstance(r.json()["servers"], dict)
    t = client.get("/tools")
    assert t.status_code == 200
    names = {x["name"] for x in t.json()["tools"]}
    assert {"file_reader", "calculator", "datetime"} <= names
