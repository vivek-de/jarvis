#!/usr/bin/env python3
"""
scripts/_sandbox_check.py — stdlib-only verification of the safety-critical logic.
═══════════════════════════════════════════════════════════════════════════════
Runs WITHOUT any third-party packages (no fastapi/httpx/pydantic), so it executes
in restricted environments where PyPI is unavailable. It exercises the pieces that
MUST be correct: DB migrations, the spend-cap tracker, and the model-router
fallback decisions. The full pytest suite (which needs fastapi/httpx) runs on the Mac.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.db import DB, run_migrations              # noqa: E402
from backend.models.routing_core import parse_slot, route_decision  # noqa: E402
from backend.models.spend import SpendTracker                   # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name}")


def _insert_cost(conn: sqlite3.Connection, provider: str, cost: float):
    conn.execute(
        "INSERT INTO llm_calls(provider, model, cost_inr, success, created_at) VALUES (?,?,?,1,?)",
        (provider, "m", cost, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "check.db"

    print("[1] migrations")
    applied = run_migrations(tmp)
    check("001_init applied", "001_init" in applied)
    check("re-run is idempotent", run_migrations(tmp) == [])
    db = DB(tmp)
    for t in ("conversations", "messages", "llm_calls", "audit_log", "schema_migrations"):
        row = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        check(f"table {t} exists", row is not None)

    print("[2] conversation persistence")
    cid = db.create_conversation("hi")
    db.add_message(cid, "user", "hello")
    db.add_message(cid, "assistant", "hi there")
    msgs = db.get_messages(cid)
    check("2 messages stored in order", len(msgs) == 2 and msgs[0]["role"] == "user")
    check("conversation_exists true", db.conversation_exists(cid))
    check("unknown conversation false", not db.conversation_exists("nope"))

    print("[3] spend cap (₹200/day)")
    st = SpendTracker(db.conn, cap_inr=200.0)
    check("empty day spend = 0", st.spent_today() == 0.0)
    check("under cap when empty", st.under_cap() is True)
    _insert_cost(db.conn, "anthropic", 150.0)
    check("spent_today = 150 after one call", abs(st.spent_today() - 150.0) < 1e-9)
    check("provider filter works", abs(st.spent_today("anthropic") - 150.0) < 1e-9)
    check("still under cap at 150", st.under_cap() is True)
    check("would_exceed(60) at 150 -> True", st.would_exceed(60.0) is True)
    _insert_cost(db.conn, "openai", 60.0)   # total 210 > 200
    check("over cap at 210", st.under_cap() is False)
    check("remaining() clamps to 0", st.remaining() == 0.0)

    print("[4] router fallback decisions")
    check("parse ollama bare", parse_slot("llama3.1:8b") == ("ollama", "llama3.1:8b"))
    check("parse cloud", parse_slot("anthropic:claude-x") == ("anthropic", "claude-x"))

    d = route_decision("GENERAL", "ollama:llama3.1:8b", "llama3.1:8b", has_key=True, under_cap=True)
    check("local slot -> ollama, no fallback", d.provider == "ollama" and not d.is_fallback)

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=False, under_cap=True)
    check("cloud without key -> fallback to ollama", d.provider == "ollama" and d.is_fallback and "No API key" in d.notice)

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=False)
    check("cloud over cap -> fallback to ollama", d.provider == "ollama" and d.is_fallback and "cap" in d.notice.lower())

    d = route_decision("CODING", "anthropic:claude-x", "llama3.1:8b", has_key=True, under_cap=True)
    check("cloud with key + budget -> cloud allowed", d.provider == "anthropic" and not d.is_fallback)

    print("[5] memory policy (Phase 2)")
    from backend.memory.policy import should_remember  # stdlib-only import
    check("secret never remembered", should_remember("my zerodha password is x").remember is False)
    check("explicit remember", should_remember("remember I prefer short replies").remember is True)
    check("preference", should_remember("always use IST, never notify at night").category == "preference")
    check("decision", should_remember("I decided to keep momentum on paper till mid-oct").category == "decision")
    check("deadline", should_remember("Amazon SDE-1 OA is on the 12th").category == "deadline")
    check("project status", should_remember("MarketGPT is built but write-up pending").category == "project")
    check("question not remembered", should_remember("what did I decide?").remember is False)
    check("chatter not remembered", should_remember("ok cool thanks").remember is False)
    check("correction wins (imp 5)", should_remember("actually the review is mid-nov").importance == 5)

    print("[6] identity files (Phase 2) — content, not OS-derived")
    idir = ROOT / "identity"
    user_md = (idir / "USER.md").read_text(encoding="utf-8") if (idir / "USER.md").exists() else ""
    soul_md = (idir / "SOUL.md").read_text(encoding="utf-8") if (idir / "SOUL.md").exists() else ""
    check("USER.md exists + names Vivek", "Vivek" in user_md)
    check("SOUL.md forbids OS-derived name", "never derive" in soul_md.lower() or "never infer" in soul_md.lower()
          or "os login" in soul_md.lower())
    check("SOUL.md carries read-only trading rule", "read-only" in soul_md.lower())

    print("[7] memory logic (Phase 3 — importance / commands / dedupe)")
    from backend.memory.commands import parse_command
    from backend.memory.dedupe import cosine_similarity, is_duplicate
    from backend.memory.importance import score_for
    check("importance correction=0.95", score_for("correction") == 0.95)
    check("importance preference=0.9", score_for("preference") == 0.9)
    check("importance project=0.8", score_for("project") == 0.8)
    check("importance chatter=0.1", score_for("chatter") == 0.1)
    check("importance default=0.5", score_for("???") == 0.5)
    check("cmd remember", (lambda c: c and c.kind == "remember")(parse_command("remember I trade NIFTY")))
    check("cmd recall", (lambda c: c and c.kind == "recall")(parse_command("what do you know about OptionIQ?")))
    check("cmd delete-all before forget", (lambda c: c and c.kind == "delete")(parse_command("delete everything about EcoCycle")))
    check("cmd forget", (lambda c: c and c.kind == "forget")(parse_command("forget my old note")))
    check("cmd none for chat", parse_command("how is the market?") is None)
    check("dedupe >=0.92 True", is_duplicate(0.93, 0.92) is True)
    check("dedupe <0.92 False", is_duplicate(0.90, 0.92) is False)
    check("cosine identical ~1", abs(cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9)

    print("[8] migration 002 SQL present + shaped")
    sql = (ROOT / "backend" / "memory" / "migrations" / "002_memories.sql").read_text()
    check("002 has vector(768)", "vector(768)" in sql)
    check("002 has HNSW index", "hnsw" in sql.lower() and "vector_cosine_ops" in sql)
    check("002 has superseded_by", "superseded_by" in sql)
    check("002 tracks migrations", "memory_schema_migrations" in sql)

    print("[9] skills (Phase 4 — loading / selection / placement handler)")
    import asyncio
    from backend.skills.registry import Skill, SkillContext, SkillRegistry
    reg = SkillRegistry.load()
    names = {s.name for s in reg.skills}
    check("loads placement_prep", "placement_prep" in names)
    check("loads project_memory", "project_memory" in names)
    check("loads trading_read", "trading_read" in names)
    check("route → placement_prep", (reg.select("solved two-sum topic:arrays") or _N()).name == "placement_prep")
    check("route → project_memory", (reg.select("where did I leave OptionIQ") or _N()).name == "project_memory")
    check("route → trading_read", (reg.select("show my portfolio nav") or _N()).name == "trading_read")
    check("no skill for chatter", reg.select("tell me a joke about cats") is None)
    # plural trigger must still route (the "my deadlines" hang was a plural miss)
    check("plural route → placement_prep (my deadlines)", (reg.select("my deadlines") or _N()).name == "placement_prep")
    check("plural does not over-match (nav != navigate)",
          Skill(name="x", description="", triggers=["nav"], instructions="", allowed_tools=[],
                permissions={}, io_schema={}, handler=None, dir=ROOT).score("please navigate home") == 0)

    # placement handler against a real temp sqlite (migration 002 already applied above)
    pskill = reg.by_name["placement_prep"]
    ctx = SkillContext(db=db, router=None, memory=None, settings=None)
    r = asyncio.run(pskill.handler(ctx, "solved two-sum topic:arrays difficulty:easy"))
    check("placement logs a solve", "two-sum" in r["reply"].lower() and db.dsa_stats()["total"] == 1)
    r = asyncio.run(pskill.handler(ctx, "deadline Amazon OA on 2026-10-05"))
    check("placement adds a deadline", "2026-10-05" in r["reply"])
    r = asyncio.run(pskill.handler(ctx, "struggled dijkstra topic:graphs"))
    check("placement flags weak topic", "graphs" in db.dsa_stats()["weak_topics"])

    print("[10] tools (Phase 5 — registry / calculator / datetime / detection / audit)")
    import json as _json

    from backend.tools import TOOL_REGISTRY, detect_tool
    from backend.tools.audit import log_tool_call
    from backend.tools.base import BaseTool, ToolPermission, ToolResult
    from backend.tools.implementations.calculator import CalculatorTool
    from backend.tools.implementations.datetime_tool import DatetimeTool
    from backend.tools.implementations.file_reader import FileReaderTool
    names = {t["name"] for t in TOOL_REGISTRY.list_all()}
    check("registry has built-in READ tools", {"file_reader", "calculator", "datetime"} <= names
          and all(t["permission"] == "READ" for t in TOOL_REGISTRY.list_all()))

    class _FakeTrade(BaseTool):
        name, description, permission = "ft", "", ToolPermission.FINANCIAL
        def _run(self, args): return ToolResult.success({"executed": True})
    check("FINANCIAL refused without confirm", _FakeTrade().run({}).ok is False)
    check("FINANCIAL allowed key present w/ confirm", _FakeTrade().run({"confirm": True}).ok is True)

    calc = CalculatorTool()
    check("calc 15*3=45", calc.run({"expression": "15*3"}).data["result"] == 45)
    check("calc 450/12=37.5", calc.run({"expression": "450/12"}).data["result"] == 37.5)
    check("calc sqrt+round", calc.run({"expression": "sqrt(16)+round(2.7)"}).data["result"] == 7.0)
    check("calc rejects code", calc.run({"expression": "__import__('os')"}).ok is False)
    check("calc rejects names", calc.run({"expression": "x+1"}).ok is False)
    check("calc div-by-zero", calc.run({"expression": "1/0"}).ok is False)

    dt = DatetimeTool()
    check("datetime now → IST", dt.run({"query": "now"}).data["tz"].startswith("IST"))
    check("datetime market bool", isinstance(dt.run({"query": "market_status"}).data["open"], bool))
    check("datetime days_until >0", dt.run({"query": "days_until:2099-12-31"}).data["days"] > 0)
    check("datetime bad date fails", dt.run({"query": "days_until:nope"}).ok is False)

    fr = FileReaderTool()
    check("file rejects /etc/passwd", fr.run({"path": "/etc/passwd"}).ok is False)

    check("detect calculator", (detect_tool("what is 150 * 3.5") or {}).get("name") == "calculator")
    check("detect datetime market", (detect_tool("is the market open now") or {}).get("name") == "datetime")
    check("detect datetime time", (detect_tool("what time is it in IST") or {}).get("name") == "datetime")
    check("detect file reader", (detect_tool("read file /tmp/x.csv") or {}).get("name") == "file_reader")
    check("detect none for chatter", detect_tool("tell me about the market trend") is None)

    log_tool_call(db.conn, "calculator", "READ", _json.dumps({"expression": "1+1"}), True, None, 2)
    row = db.conn.execute("SELECT actor, permission, approved FROM audit_log WHERE action='tool_call'").fetchone()
    check("audit row written", row is not None and row[0] == "agent" and row[1] == "READ" and row[2] == 1)

    print("[11] MCP (Phase 6 — config / wrapping / startup / failure, all mocked)")
    from backend.mcp import registry as _regmod
    from backend.mcp.client import parse_permission
    from backend.mcp.registry import MCPRegistry, MCPTool
    from backend.tools.base import ToolRegistry as _TR

    servers = MCPRegistry.load_config()      # real mcp/servers.json
    check("config loads filesystem server", any(s.get("name") == "filesystem" for s in servers))
    check("missing config → []", MCPRegistry.load_config(tmp.parent / "nope.json") == [])
    check("parse_permission defaults READ", parse_permission("weird") == ToolPermission.READ)

    class _FakeMCP:
        def __init__(self, cfg):
            self.name = cfg["name"]; self.permission = parse_permission(cfg.get("permission"))
            self.enabled = cfg.get("enabled", True); self.error = None; self.stopped = False
            self._ok = cfg.get("_start_ok", True); self._tools = cfg.get("_tools", [])
        async def start(self):
            if not self.enabled: self.error = "disabled"; return False
            if not self._ok: self.error = "boom"; return False
            return True
        async def list_tools(self): return self._tools
        async def call_tool(self, name, arguments=None): return ToolResult.success({"tool": name, "echo": arguments})
        async def stop(self): self.stopped = True

    fc = _FakeMCP({"name": "fs", "permission": "READ"})
    wt = MCPTool(fc, "read_file", "r", {}, ToolPermission.READ)
    check("MCPTool name is server.tool", wt.name == "fs.read_file")
    check("MCPTool async execute works", asyncio.run(wt.execute({"path": "x"})).data["tool"] == "read_file")
    check("MCPTool sync _run is a safe no-op", wt.execute is not None and wt._run({}).ok is False)
    fin = MCPTool(_FakeMCP({"name": "bank", "permission": "FINANCIAL"}), "transfer", "", {}, ToolPermission.FINANCIAL)
    check("MCP FINANCIAL refused w/o confirm", asyncio.run(fin.execute({})).ok is False)
    check("MCP FINANCIAL allowed w/ confirm", asyncio.run(fin.execute({"confirm": True})).ok is True)

    _regmod.MCPServerClient = _FakeMCP  # inject fake for startup

    tr = _TR(); r1 = MCPRegistry()
    MCPRegistry.load_config = staticmethod(lambda *a, **k: [{"name": "fs", "enabled": True,
        "permission": "READ", "_tools": [{"name": "read_file", "description": "r", "inputSchema": {}},
                                         {"name": "write_file", "description": "w", "inputSchema": {}}]}])
    asyncio.run(r1.startup(tr))
    check("startup registers 2 tools", r1.get_server_status()["fs"]["tool_count"] == 2)
    check("registered tool present", tr.get("fs.read_file") is not None)
    asyncio.run(r1.shutdown()); check("shutdown clears clients", r1.clients == [])

    tr = _TR(); r2 = MCPRegistry()
    MCPRegistry.load_config = staticmethod(lambda *a, **k: [{"name": "off", "enabled": False, "permission": "READ"}])
    asyncio.run(r2.startup(tr))
    check("disabled server skipped", r2.get_server_status()["off"]["enabled"] is False and len(tr) == 0)

    tr = _TR(); r3 = MCPRegistry()
    MCPRegistry.load_config = staticmethod(lambda *a, **k: [{"name": "broken", "enabled": True,
        "permission": "READ", "_start_ok": False}])
    asyncio.run(r3.startup(tr))
    check("startup failure handled (no crash)", r3.get_server_status()["broken"]["error"] == "boom" and len(tr) == 0)

    print("[12] web tools (Phase 7 — registry / SSRF / scheme / detection, network mocked)")
    import sys as _sys
    import types as _types

    from backend.tools import TOOL_REGISTRY as _TREG
    from backend.tools import detect_tool as _detect
    from backend.tools.implementations.web_search import WebSearchTool
    _wnames = {t["name"] for t in _TREG.list_all()}
    check("web tools registered", {"web_search", "web_fetch"} <= _wnames)
    check("web_search empty query rejected", WebSearchTool().run({"query": "  "}).ok is False)

    def _fake_ddgs(results):
        _mod = _types.ModuleType("duckduckgo_search")
        class _DDGS:
            def __init__(self, timeout=None): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def text(self, query, max_results=5): return results[:max_results]
        _mod.DDGS = _DDGS
        _sys.modules["duckduckgo_search"] = _mod

    _fake_ddgs([{"title": str(i), "href": f"https://s{i}.com", "body": ""} for i in range(30)])
    _sr = WebSearchTool().run({"query": "q", "max_results": 50})
    check("web_search caps at 10", _sr.ok and _sr.data["count"] == 10)
    _fake_ddgs([{"title": "bad", "href": "https://grabify.link/x", "body": ""},
                {"title": "good", "href": "https://good.com", "body": ""}])
    _sr2 = WebSearchTool().run({"query": "q"})
    check("web_search drops blocked domain", _sr2.data["count"] == 1 and
          _sr2.data["results"][0]["url"] == "https://good.com")
    _sys.modules.pop("duckduckgo_search", None)

    # web_fetch SSRF blocking uses real literal private IPs (no DNS, no httpx needed)
    from backend.tools.implementations.web_fetch import WebFetchTool, _normalize
    check("web_fetch scheme prepend", _normalize("example.com/x") == "https://example.com/x")
    _wf = WebFetchTool()
    check("web_fetch blocks localhost", _wf.run({"url": "http://localhost"}).ok is False)
    check("web_fetch blocks 10.x", _wf.run({"url": "http://10.0.0.1"}).ok is False)
    check("web_fetch blocks 192.168.x", _wf.run({"url": "http://192.168.1.1"}).ok is False)
    check("web_fetch blocks 169.254.x", _wf.run({"url": "http://169.254.1.1"}).ok is False)
    check("web_fetch blocks ::1", _wf.run({"url": "http://[::1]"}).ok is False)

    check("detect web_search", (_detect("search for NIFTY 50 today") or {}).get("name") == "web_search")
    check("detect web_search query", (_detect("search for NIFTY 50 today") or {}).get("args", {}).get("query") == "NIFTY 50 today")
    check("detect google →search", (_detect("google best laptops 2026") or {}).get("name") == "web_search")
    check("detect web_fetch url", (_detect("fetch https://economictimes.indiatimes.com") or {}).get("name") == "web_fetch")
    check("detect open url →fetch", (_detect("open url example.com") or {}).get("name") == "web_fetch")

    db.close()
    print(f"\nSANDBOX CHECK: {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


class _N:  # tiny stand-in so a None select doesn't crash the .name access in checks
    name = None


if __name__ == "__main__":
    sys.exit(main())
