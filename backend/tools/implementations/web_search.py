"""
backend/tools/implementations/web_search.py — DuckDuckGo web search (Phase 7, READ).
═══════════════════════════════════════════════════════════════════════════════
No API key: uses the `duckduckgo_search` (DDGS) library. The library is imported
lazily inside _run so this module stays importable where the dep isn't installed
(e.g. the stdlib sandbox). Results are capped at 10, spam/blocked domains are
dropped, and search output is DATA — never instructions to act on.
"""
from __future__ import annotations

from urllib.parse import urlparse

from ..base import BaseTool, ToolPermission, ToolResult

HARD_MAX_RESULTS = 10
SEARCH_TIMEOUT_S = 10
# Domains we never surface (spam / malware / content farms). Substring match on host.
BLOCKED_DOMAINS = {
    "grabify.link", "iplogger.org", "iplogger.com", "spam.example",
}


def _blocked(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) or d in host for d in BLOCKED_DOMAINS)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = ("Search the web (DuckDuckGo, no API key). Returns up to 10 "
                   "{title, url, snippet} results. Read-only.")
    permission = ToolPermission.READ
    schema = {"type": "object",
              "properties": {"query": {"type": "string"},
                             "max_results": {"type": "integer", "default": 5}},
              "required": ["query"]}

    def _run(self, args: dict) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.fail("no 'query' provided")
        try:
            n = int(args.get("max_results", 5))
        except (TypeError, ValueError):
            n = 5
        n = max(1, min(n, HARD_MAX_RESULTS))

        try:
            from duckduckgo_search import DDGS
        except Exception as e:  # dep missing
            return ToolResult.fail(f"duckduckgo_search not installed: {e}")

        try:
            with DDGS(timeout=SEARCH_TIMEOUT_S) as ddgs:
                raw = list(ddgs.text(query, max_results=n))
        except Exception as e:
            return ToolResult.fail(f"search failed: {e}")

        results = []
        for r in raw:
            url = r.get("href") or r.get("url") or ""
            if not url or _blocked(url):
                continue
            results.append({"title": r.get("title", ""), "url": url,
                            "snippet": r.get("body", "") or r.get("snippet", "")})
            if len(results) >= HARD_MAX_RESULTS:
                break
        return ToolResult.success({"query": query, "count": len(results), "results": results})
