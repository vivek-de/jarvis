def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"                 # stub_ollama makes ollama.ok True
    assert body["db"]["ok"] is True
    assert body["ollama"]["ok"] is True
    assert body["spend_cap_inr"] == 200.0
    assert body["app"]["name"] == "jarvis"


def test_conversation_404(client):
    r = client.get("/conversations/does-not-exist")
    assert r.status_code == 404
