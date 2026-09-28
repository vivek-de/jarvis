"""
backend/tools/implementations/web_fetch.py — fetch + extract a web page (Phase 7, READ).
═══════════════════════════════════════════════════════════════════════════════
Fetches a URL and returns its main text, title, or links. Two safety layers:
  • SSRF — backend/security/ssrf.check_url with an EMPTY allowlist, so every
    private/loopback/link-local host is blocked (127.x, 10.x, 192.168.x, 169.254.x,
    ::1, …). Re-checked after redirects so a public URL can't bounce to an internal one.
  • Size — the response body is capped at 100KB (truncated with a notice).

httpx + BeautifulSoup are imported lazily so the module stays importable without them.
Fetched page content is DATA, never instructions.
"""
from __future__ import annotations

from ...security.ssrf import SSRFError, check_url
from ..base import BaseTool, ToolPermission, ToolResult

MAX_BYTES = 100 * 1024
FETCH_TIMEOUT_S = 15
USER_AGENT = "JARVIS/0.1 (personal assistant)"
_EMPTY_ALLOWLIST: set[str] = set()   # web browsing trusts NO private hosts


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = ("Fetch a web page and extract its text, title, or links. "
                   "SSRF-guarded (no private IPs), 100KB cap, 15s timeout. Read-only.")
    permission = ToolPermission.READ
    schema = {"type": "object",
              "properties": {"url": {"type": "string"},
                             "extract": {"type": "string", "enum": ["text", "title", "links"]}},
              "required": ["url"]}

    def _run(self, args: dict) -> ToolResult:
        url = _normalize(args.get("url", ""))
        if not url:
            return ToolResult.fail("no 'url' provided")
        extract = (args.get("extract") or "text").lower()
        if extract not in ("text", "title", "links"):
            return ToolResult.fail(f"bad extract '{extract}' — use text|title|links")

        try:
            check_url(url, _EMPTY_ALLOWLIST)         # SSRF: block private/loopback
        except SSRFError as e:
            return ToolResult.fail(f"blocked by SSRF guard: {e}")

        try:
            import httpx
        except Exception as e:
            return ToolResult.fail(f"httpx not installed: {e}")

        try:
            with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as client:
                resp = client.get(url)
        except httpx.TimeoutException:
            return ToolResult.fail(f"timed out after {FETCH_TIMEOUT_S}s fetching {url}")
        except Exception as e:
            return ToolResult.fail(f"fetch failed: {e}")

        # a redirect may have landed on a private host — re-check the final URL
        try:
            check_url(str(resp.url), _EMPTY_ALLOWLIST)
        except SSRFError as e:
            return ToolResult.fail(f"redirect blocked by SSRF guard: {e}")

        if resp.status_code >= 400:
            return ToolResult.fail(f"HTTP {resp.status_code} from {url}")

        body = resp.content[:MAX_BYTES]
        truncated = len(resp.content) > MAX_BYTES
        html = body.decode(resp.encoding or "utf-8", errors="replace")

        try:
            from bs4 import BeautifulSoup
        except Exception as e:
            return ToolResult.fail(f"beautifulsoup4 not installed: {e}")

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()

        if extract == "title":
            title = (soup.title.string if soup.title and soup.title.string else "").strip()
            return ToolResult.success({"url": str(resp.url), "title": title})

        if extract == "links":
            links = []
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                if a["href"].startswith(("http://", "https://")):
                    links.append({"text": text, "href": a["href"]})
                if len(links) >= 100:
                    break
            return ToolResult.success({"url": str(resp.url), "count": len(links), "links": links})

        # default: main text content
        main = soup.find("article") or soup.find("main") or soup.body or soup
        text = main.get_text(separator="\n", strip=True)
        text = "\n".join(line for line in text.splitlines() if line.strip())
        if truncated:
            text += f"\n\n[truncated at {MAX_BYTES} bytes]"
        return ToolResult.success({"url": str(resp.url), "chars": len(text), "text": text})
