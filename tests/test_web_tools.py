"""Phase 7 — web browsing tools: search + fetch. All network is mocked.

DDGS is faked via a stub module injected into sys.modules; httpx.Client is
monkeypatched; the SSRF guard is exercised with real literal private IPs (no DNS)
and bypassed only for the happy-path fetch tests.
"""
import sys
import types

from backend.tools import detect_tool
from backend.tools.implementations import web_fetch as WF
from backend.tools.implementations.web_fetch import WebFetchTool
from backend.tools.implementations.web_search import WebSearchTool


# ── web search (fake DDGS) ────────────────────────────────────────────────────
def _install_fake_ddgs(monkeypatch, results):
    mod = types.ModuleType("duckduckgo_search")

    class DDGS:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=5):
            return results[:max_results]

    mod.DDGS = DDGS
    monkeypatch.setitem(sys.modules, "duckduckgo_search", mod)


def test_web_search_returns_results(monkeypatch):
    _install_fake_ddgs(monkeypatch, [
        {"title": "NIFTY 50", "href": "https://a.com", "body": "snippet a"},
        {"title": "News", "href": "https://b.com", "body": "snippet b"}])
    r = WebSearchTool().run({"query": "NIFTY 50 today", "max_results": 5})
    assert r.ok and r.data["count"] == 2
    assert r.data["results"][0] == {"title": "NIFTY 50", "url": "https://a.com", "snippet": "snippet a"}


def test_web_search_empty_query_rejected():
    assert WebSearchTool().run({"query": "   "}).ok is False


def test_web_search_drops_blocked_domains(monkeypatch):
    _install_fake_ddgs(monkeypatch, [
        {"title": "bad", "href": "https://grabify.link/abc", "body": ""},
        {"title": "good", "href": "https://good.com", "body": ""}])
    r = WebSearchTool().run({"query": "q"})
    assert r.data["count"] == 1 and r.data["results"][0]["url"] == "https://good.com"


def test_web_search_caps_at_ten(monkeypatch):
    _install_fake_ddgs(monkeypatch, [{"title": str(i), "href": f"https://s{i}.com", "body": ""}
                                     for i in range(30)])
    r = WebSearchTool().run({"query": "q", "max_results": 50})
    assert r.data["count"] == 10


# ── web fetch (fake httpx) ────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, content=b"", status_code=200, url="https://example.com", encoding="utf-8"):
        self.content = content
        self.status_code = status_code
        self.url = url
        self.encoding = encoding


def _fake_httpx(monkeypatch, resp=None, raise_timeout=False, capture=None):
    import httpx

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            if capture is not None:
                capture["url"] = url
            if raise_timeout:
                raise httpx.TimeoutException("slow")
            return resp if resp is not None else FakeResp(content=b"<html><body>ok</body></html>", url=url)

    monkeypatch.setattr(httpx, "Client", FakeClient)


def test_web_fetch_text_strips_scripts(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)     # bypass DNS/SSRF for happy path
    html = (b"<html><head><title>Hi</title></head><body>"
            b"<script>evil()</script><main>Hello <b>world</b></main></body></html>")
    _fake_httpx(monkeypatch, FakeResp(content=html, url="https://example.com"))
    r = WebFetchTool().run({"url": "https://example.com", "extract": "text"})
    assert r.ok and "Hello" in r.data["text"] and "evil" not in r.data["text"]


def test_web_fetch_title(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)
    _fake_httpx(monkeypatch, FakeResp(content=b"<html><head><title>My Page</title></head><body>x</body></html>"))
    r = WebFetchTool().run({"url": "https://example.com", "extract": "title"})
    assert r.ok and r.data["title"] == "My Page"


def test_web_fetch_links(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)
    html = b"<html><body><a href='https://x.com'>X</a><a href='/rel'>rel</a></body></html>"
    _fake_httpx(monkeypatch, FakeResp(content=html))
    r = WebFetchTool().run({"url": "https://example.com", "extract": "links"})
    assert r.ok and r.data["count"] == 1 and r.data["links"][0]["href"] == "https://x.com"


def test_web_fetch_ssrf_blocks_private_ips():
    for u in ["http://localhost", "http://10.0.0.1", "http://192.168.1.1",
              "http://169.254.1.1", "http://[::1]"]:
        r = WebFetchTool().run({"url": u})
        assert r.ok is False and "SSRF" in r.error, u


def test_web_fetch_prepends_scheme(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)
    cap = {}
    _fake_httpx(monkeypatch, FakeResp(content=b"<html><body>ok</body></html>"), capture=cap)
    r = WebFetchTool().run({"url": "example.com/page"})
    assert r.ok and cap["url"] == "https://example.com/page"


def test_web_fetch_timeout(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)
    _fake_httpx(monkeypatch, raise_timeout=True)
    r = WebFetchTool().run({"url": "https://example.com"})
    assert r.ok is False and "timed out" in r.error


def test_web_fetch_http_error(monkeypatch):
    monkeypatch.setattr(WF, "check_url", lambda u, a: u)
    _fake_httpx(monkeypatch, FakeResp(content=b"nope", status_code=404))
    r = WebFetchTool().run({"url": "https://example.com"})
    assert r.ok is False and "404" in r.error


# ── detection ─────────────────────────────────────────────────────────────────
def test_detect_web_tools():
    assert detect_tool("search for NIFTY 50 today")["name"] == "web_search"
    assert detect_tool("search for NIFTY 50 today")["args"]["query"] == "NIFTY 50 today"
    assert detect_tool("look up python asyncio")["name"] == "web_search"
    assert detect_tool("google best laptops 2026")["name"] == "web_search"
    assert detect_tool("find info about the RBI repo rate")["name"] == "web_search"
    assert detect_tool("fetch https://economictimes.indiatimes.com")["name"] == "web_fetch"
    assert detect_tool("open url example.com")["name"] == "web_fetch"
    assert detect_tool("read page https://a.com/b")["name"] == "web_fetch"
    # "what does X say" with no URL should NOT fire web_fetch
    assert detect_tool("what does the policy say") is None or \
        detect_tool("what does the policy say")["name"] != "web_fetch"
