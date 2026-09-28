"""Shared pytest fixtures. These tests need fastapi/httpx/pytest installed
(they run on the Mac inside the venv, not in the restricted sandbox)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings                       # noqa: E402
from backend.models.providers.base import ModelResult     # noqa: E402
from backend.models.providers.ollama import OllamaProvider  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Isolated settings on a temp DB, ignoring any real .env / env prefix."""
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "test.db"),
        daily_spend_cap_inr=200.0,
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.1:8b",
        rate_limit_per_min=1000,
        mcp_enabled=False,        # never launch MCP subprocesses during tests
        scheduler_enabled=False,  # never start the background scheduler loop during tests
    )


@pytest.fixture
def stub_ollama(monkeypatch):
    """Replace the network calls of OllamaProvider so tests never hit real Ollama."""
    async def fake_generate(self, messages, model=None, **opts):
        return ModelResult(text="pong", provider="ollama", model=model or self.default_model,
                           prompt_tokens=5, completion_tokens=1, cost_inr=0.0,
                           latency_ms=1, success=True)

    async def fake_health(self):
        return {"provider": "ollama", "ok": True, "models": ["llama3.1:8b"]}

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)
    monkeypatch.setattr(OllamaProvider, "health", fake_health)


@pytest.fixture
def client(settings, stub_ollama):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
