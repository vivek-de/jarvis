"""Phase 12 — web dashboard: /chat shape + static /app mounting.

The frontend build isn't required for these tests — a placeholder frontend/dist/index.html
is committed so the StaticFiles mount works before `npm run build`.
"""


def test_chat_returns_dashboard_shape(client):
    r = client.post("/chat", json={"message": "hello", "channel": "web"})
    assert r.status_code == 200
    body = r.json()
    for key in ("response", "tool_used", "skill", "latency_ms", "cost_inr"):
        assert key in body
    assert body["response"]                       # stub_ollama returns "pong"
    assert body["skill"] is None                  # plain chat → no skill


def test_chat_requires_message(client):
    assert client.post("/chat", json={}).status_code == 422


def test_chat_still_returns_full_payload(client):
    body = client.post("/chat", json={"message": "hi"}).json()
    assert "session_id" in body and "trace" in body and "reply" in body   # back-compat


def test_app_root_serves_200(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_app_index_mentions_jarvis(client):
    assert "JARVIS" in client.get("/app/").text


def test_app_missing_asset_404(client):
    assert client.get("/app/definitely-not-here.js").status_code == 404


def test_health_still_ok(client):
    r = client.get("/health")
    assert r.status_code == 200 and "status" in r.json()
