"""
backend/tools — Phase 5 tool system.
═══════════════════════════════════════════════════════════════════════════════
Builds a global TOOL_REGISTRY with the three built-in READ tools, and exposes
detect_tool(): a deterministic, LLM-free matcher that maps a user message to a
(tool, args) pair. The agent runs the matched tool before the LLM and injects the
result into context. Detection is pure-Python (regex) so it's unit-testable.
"""
from __future__ import annotations

import re

from .base import BaseTool, ToolPermission, ToolRegistry, ToolResult  # noqa: F401
from .implementations.calculator import CalculatorTool
from .implementations.datetime_tool import DatetimeTool
from .implementations.file_reader import FileReaderTool
from .implementations.web_fetch import WebFetchTool
from .implementations.web_search import WebSearchTool

TOOL_REGISTRY = ToolRegistry()
for _t in (FileReaderTool(), CalculatorTool(), DatetimeTool(), WebSearchTool(), WebFetchTool()):
    TOOL_REGISTRY.register(_t)

# ── detection patterns ──────────────────────────────────────────────────────
_FILE_RE = re.compile(r"\b(?:read|open|show|cat)\s+(?:the\s+)?file\s+[\"']?([^\"'\n]+?)[\"']?\s*$", re.I)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# a math expression: digits joined by operators, or a whitelisted function call
_MATH_RE = re.compile(r"((?:sqrt|log|round)\s*\([^)]*\)|[0-9][0-9.\s]*(?:[-+*/%^][0-9.\s()]*)+)", re.I)
# a URL or bare domain (used to route web_fetch)
_URL_RE = re.compile(r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?)", re.I)
_SEARCH_RE = re.compile(r"\b(search(?:\s+for)?|look\s+up|google|find\s+info(?:rmation)?\s+about|web\s+search)\b", re.I)
_FETCH_RE = re.compile(r"\b(open\s+url|fetch|read\s+page|browse|what\s+does)\b", re.I)


def detect_tool(message: str) -> dict | None:
    """Return {'name', 'args', 'permission'} for the first matching tool, else None."""
    text = message.strip()
    low = text.lower()

    # 1) file reader — "read file X" / "open file X"
    m = _FILE_RE.search(text)
    if m:
        return {"name": "file_reader", "args": {"path": m.group(1).strip()},
                "permission": ToolPermission.READ.value}

    # 2) web fetch — "open url X" / "fetch X" / "read page X" / "what does X say"
    #    (needs a URL/domain in the message; checked before search so an explicit
    #    URL isn't turned into a search query)
    fm = _FETCH_RE.search(low)
    if fm:
        um = _URL_RE.search(text)
        if um:
            return {"name": "web_fetch", "args": {"url": um.group(1).strip().rstrip(".,)"),
                                                  "extract": "text"},
                    "permission": ToolPermission.READ.value}

    # 3) web search — "search for X" / "look up X" / "google X" / "find info about X"
    sm = _SEARCH_RE.search(text)
    if sm:
        query = text[sm.end():].strip(" :\"'?.")
        if query:
            return {"name": "web_search", "args": {"query": query, "max_results": 5},
                    "permission": ToolPermission.READ.value}

    # 4) datetime — market status / days-until / clock (before calculator, so
    #    "days until 2026-12-31" isn't misread as arithmetic)
    if "market" in low and any(w in low for w in ("open", "close", "status", "trading")):
        return {"name": "datetime", "args": {"query": "market_status"},
                "permission": ToolPermission.READ.value}
    if "days until" in low or "days till" in low or "days to" in low:
        d = _DATE_RE.search(low)
        if d:
            return {"name": "datetime", "args": {"query": f"days_until:{d.group(1)}"},
                    "permission": ToolPermission.READ.value}
    if any(p in low for p in ("what time", "time is it", "time in ist", "current time",
                              "what's the date", "whats the date", "today's date", "what day",
                              "day is it", "date today")):
        return {"name": "datetime", "args": {"query": "now"},
                "permission": ToolPermission.READ.value}

    # 3) calculator — explicit ask or a "what is <math>" with an operator present
    wants_calc = bool(re.search(r"\b(calculate|compute|evaluate)\b", low)) or \
        (bool(re.search(r"\b(what\s+is|what's|whats|how much is)\b", low)) and bool(_MATH_RE.search(text)))
    if wants_calc:
        region = re.split(r"\b(calculate|compute|evaluate)\b", text, maxsplit=1, flags=re.I)[-1]
        mm = _MATH_RE.search(region) or _MATH_RE.search(text)
        if mm:
            expr = mm.group(1).replace("^", "**").strip()
            return {"name": "calculator", "args": {"expression": expr},
                    "permission": ToolPermission.READ.value}

    return None
