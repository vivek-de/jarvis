"""
backend/tools/implementations/file_reader.py — allowlisted file reads (Phase 5, READ).
═══════════════════════════════════════════════════════════════════════════════
Path allowlist works like the SSRF guard: a file may be read ONLY if its real,
symlink-resolved path lives inside an allowed directory (jarvis/data or ~/Downloads).
This blocks path traversal ("../../etc/passwd") and symlink escapes. Only text-ish
extensions are allowed, and reads are capped at 50KB (truncated with a notice).
"""
from __future__ import annotations

from pathlib import Path

from ..base import BaseTool, ToolPermission, ToolResult

MAX_BYTES = 50 * 1024
ALLOWED_EXT = {".txt", ".md", ".json", ".csv"}
# backend/tools/implementations/file_reader.py → parents[3] = project root
_ROOT = Path(__file__).resolve().parents[3]


def _allowed_dirs() -> list[Path]:
    dirs = [_ROOT / "data", Path.home() / "Downloads"]
    out = []
    for d in dirs:
        try:
            out.append(d.resolve())
        except Exception:
            out.append(d)
    return out


class FileReaderTool(BaseTool):
    name = "file_reader"
    description = ("Read a small text file (.txt/.md/.json/.csv, max 50KB) from the "
                   "jarvis data folder or ~/Downloads. Path-allowlisted; nothing else is readable.")
    permission = ToolPermission.READ
    schema = {"type": "object",
              "properties": {"path": {"type": "string", "description": "absolute or relative file path"}},
              "required": ["path"]}

    def _run(self, args: dict) -> ToolResult:
        raw = (args.get("path") or "").strip()
        if not raw:
            return ToolResult.fail("no 'path' provided")

        try:
            target = Path(raw).expanduser().resolve()
        except Exception as e:
            return ToolResult.fail(f"invalid path: {e}")

        allowed = _allowed_dirs()
        if not any(self._within(target, d) for d in allowed):
            names = ", ".join(str(d) for d in allowed)
            return ToolResult.fail(f"path not allowed — reads are restricted to: {names}")

        if target.suffix.lower() not in ALLOWED_EXT:
            return ToolResult.fail(
                f"unsupported extension '{target.suffix}' — allowed: {sorted(ALLOWED_EXT)}")

        if not target.exists() or not target.is_file():
            return ToolResult.fail(f"file not found: {target}")

        data = target.read_bytes()
        truncated = len(data) > MAX_BYTES
        text = data[:MAX_BYTES].decode("utf-8", errors="replace")
        notice = f"\n\n[truncated at {MAX_BYTES} bytes; file is {len(data)} bytes]" if truncated else ""
        return ToolResult.success({"path": str(target), "bytes": len(data),
                                   "truncated": truncated, "content": text + notice})

    @staticmethod
    def _within(target: Path, directory: Path) -> bool:
        try:
            target.relative_to(directory)
            return True
        except ValueError:
            return False
