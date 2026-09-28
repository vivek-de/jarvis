"""Phase 5 — tool system: file reader, calculator, datetime, audit, detection."""
import json

from backend.database.db import DB, run_migrations
from backend.tools import TOOL_REGISTRY, detect_tool
from backend.tools.audit import log_tool_call
from backend.tools.base import BaseTool, ToolPermission, ToolRegistry, ToolResult
from backend.tools.implementations.calculator import CalculatorTool
from backend.tools.implementations.datetime_tool import DatetimeTool
from backend.tools.implementations.file_reader import FileReaderTool


# ── registry & permissions ───────────────────────────────────────────────────
def test_registry_has_builtin_read_tools():
    names = {t["name"] for t in TOOL_REGISTRY.list_all()}
    assert {"file_reader", "calculator", "datetime"} <= names   # web tools added in Phase 7
    for t in TOOL_REGISTRY.list_all():
        assert t["permission"] == "READ"


def test_financial_tool_refused_without_confirm():
    class FakeTrade(BaseTool):
        name = "fake_trade"
        description = "test-only"
        permission = ToolPermission.FINANCIAL

        def _run(self, args):
            return ToolResult.success({"executed": True})

    t = FakeTrade()
    assert t.run({}).ok is False                 # no confirm → refused, never executed
    assert t.run({"confirm": False}).ok is False
    assert "refused" in t.run({}).error.lower()


# ── file reader ──────────────────────────────────────────────────────────────
def test_file_reader_valid(tmp_path, monkeypatch):
    f = tmp_path / "note.txt"
    f.write_text("hello jarvis", encoding="utf-8")
    monkeypatch.setattr("backend.tools.implementations.file_reader._allowed_dirs",
                        lambda: [tmp_path.resolve()])
    r = FileReaderTool().run({"path": str(f)})
    assert r.ok and "hello jarvis" in r.data["content"]


def test_file_reader_rejects_outside_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.tools.implementations.file_reader._allowed_dirs",
                        lambda: [(tmp_path / "allowed").resolve()])
    r = FileReaderTool().run({"path": "/etc/passwd"})
    assert r.ok is False and "not allowed" in r.error


def test_file_reader_rejects_unsupported_extension(tmp_path, monkeypatch):
    f = tmp_path / "run.py"
    f.write_text("print('x')", encoding="utf-8")
    monkeypatch.setattr("backend.tools.implementations.file_reader._allowed_dirs",
                        lambda: [tmp_path.resolve()])
    r = FileReaderTool().run({"path": str(f)})
    assert r.ok is False and "unsupported extension" in r.error


def test_file_reader_truncates_large_file(tmp_path, monkeypatch):
    from backend.tools.implementations import file_reader as fr
    f = tmp_path / "big.txt"
    f.write_text("A" * (fr.MAX_BYTES + 100), encoding="utf-8")
    monkeypatch.setattr(fr, "_allowed_dirs", lambda: [tmp_path.resolve()])
    r = fr.FileReaderTool().run({"path": str(f)})
    assert r.ok and r.data["truncated"] is True


# ── calculator ───────────────────────────────────────────────────────────────
def test_calculator_basic_math():
    assert CalculatorTool().run({"expression": "15*3"}).data["result"] == 45
    assert CalculatorTool().run({"expression": "450/12"}).data["result"] == 37.5
    assert CalculatorTool().run({"expression": "2**10"}).data["result"] == 1024
    assert CalculatorTool().run({"expression": "sqrt(16) + round(2.7)"}).data["result"] == 7.0


def test_calculator_rejects_code_and_names():
    assert CalculatorTool().run({"expression": "__import__('os').system('ls')"}).ok is False
    assert CalculatorTool().run({"expression": "x + 1"}).ok is False
    assert CalculatorTool().run({"expression": "1/0"}).ok is False
    assert CalculatorTool().run({"expression": "not a number"}).ok is False


# ── datetime ─────────────────────────────────────────────────────────────────
def test_datetime_now():
    r = DatetimeTool().run({"query": "now"})
    assert r.ok and "IST" in r.data["tz"] and r.data["day_of_week"]


def test_datetime_market_status():
    r = DatetimeTool().run({"query": "market_status"})
    assert r.ok and isinstance(r.data["open"], bool) and "IST" in r.data["session"]


def test_datetime_days_until():
    r = DatetimeTool().run({"query": "days_until:2099-12-31"})
    assert r.ok and r.data["days"] > 0
    assert DatetimeTool().run({"query": "days_until:not-a-date"}).ok is False


# ── detection ────────────────────────────────────────────────────────────────
def test_detect_tool_routing():
    assert detect_tool("what is 150 * 3.5")["name"] == "calculator"
    assert detect_tool("calculate 15*3")["name"] == "calculator"
    assert detect_tool("is the market open now")["name"] == "datetime"
    assert detect_tool("what time is it in IST")["name"] == "datetime"
    assert detect_tool("how many days until 2026-12-31")["args"]["query"] == "days_until:2026-12-31"
    assert detect_tool("read file /tmp/report.csv")["name"] == "file_reader"
    assert detect_tool("tell me about the market trend") is None   # no operator, not status


# ── audit ────────────────────────────────────────────────────────────────────
def test_audit_log_writes(tmp_path):
    dbf = tmp_path / "a.db"
    run_migrations(dbf)
    db = DB(dbf)
    log_tool_call(db.conn, "calculator", "READ", json.dumps({"expression": "1+1"}),
                  True, None, 3)
    row = db.conn.execute(
        "SELECT actor, action, permission, approved FROM audit_log WHERE action='tool_call'"
    ).fetchone()
    assert row["actor"] == "agent" and row["action"] == "tool_call"
    assert row["permission"] == "READ" and row["approved"] == 1
    db.close()
