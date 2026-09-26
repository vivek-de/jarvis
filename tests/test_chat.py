def test_chat_persists_and_returns_trace(client):
    r = client.post("/chat", json={"message": "ping"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "pong"               # from stub_ollama
    sid = body["session_id"]
    assert sid
    tr = body["trace"]
    assert tr["provider"] == "ollama"
    assert tr["success"] is True
    assert tr["cost_inr"] == 0.0                  # local is free
    assert tr["is_fallback"] is False

    # history persisted: user + assistant
    conv = client.get(f"/conversations/{sid}").json()
    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant"]
    assert conv["messages"][0]["content"] == "ping"


def test_chat_continues_session(client):
    r1 = client.post("/chat", json={"message": "first"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"message": "second", "session_id": sid})
    conv = client.get(f"/conversations/{sid}").json()
    # 2 user + 2 assistant
    assert len(conv["messages"]) == 4


def test_chat_handles_model_failure(client, monkeypatch):
    # make the provider fail → API still 200, reply is a clean error, nothing crashes
    from backend.models.providers.base import ModelResult
    from backend.models.providers.ollama import OllamaProvider

    async def failing(self, messages, model=None, **opts):
        return ModelResult(text="", provider="ollama", model=model or "llama3.1:8b",
                           success=False, error="ollama unreachable: refused")

    monkeypatch.setattr(OllamaProvider, "generate", failing)
    body = client.post("/chat", json={"message": "hi"}).json()
    assert "failed" in body["reply"].lower()
    assert body["trace"]["success"] is False
