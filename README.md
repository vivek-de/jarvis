# JARVIS

A private, local-first AI assistant. **Phase 1 = Foundation**: config, structured
logging, a model router (local Ollama now; cloud providers key-gated with a daily
spend cap), a persistent chat agent, health checks, an HTTP API, a CLI, and tests.

Runs **fully on local Ollama** with an empty `.env`. Cloud providers are optional.
It is read-only with respect to trading and never places orders (see `SECURITY.md`).

> Runtime choice: a thin custom FastAPI tool-use loop (not an agent framework).
> Rationale in `docs/ARCHITECTURE.md`.

## Requirements
- Python 3.10+ (`python3`, `pip3`)
- [Ollama](https://ollama.com) running with `llama3.1:8b`:
  `ollama serve` and `ollama pull llama3.1:8b`

## Setup
```bash
cd ~/Desktop/jarvis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults are fine; edit only to add cloud keys
```

## Run the server
```bash
source .venv/bin/activate
uvicorn backend.main:app --host 127.0.0.1 --port 8100
```
Then in another terminal:
```bash
curl -s http://127.0.0.1:8100/health | python3 -m json.tool
```

## Chat from the terminal
```bash
source .venv/bin/activate
python3 scripts/chat.py
```

## Run the tests
```bash
source .venv/bin/activate
pytest
```

## Safety-logic smoke test (no third-party deps needed)
```bash
python3 scripts/_sandbox_check.py
```
Exercises migrations, the spend cap, and the router fallback logic using only the
standard library.

## Layout
```
backend/   config, logging, main (FastAPI)
  api/       routes: /health, /chat, /conversations/{id}
  agent/     conversation loop + exec trace
  models/    router, spend cap, providers (ollama working, cloud stubs)
  database/  sqlite + versioned migrations
  security/  rate limiting, SSRF guard
  memory/ tools/ skills/ automation/ integrations/ trading/   (placeholders for later phases)
identity/  SOUL/USER/MEMORY/AGENTS/TOOLS .md   (templates for Phase 2)
scripts/   chat.py (CLI), _sandbox_check.py
tests/     pytest suite
docs/      ARCHITECTURE.md
```

## Config (env, prefix `JARVIS_`)
See `.env.example`. Key ones: `JARVIS_OLLAMA_MODEL`, the `JARVIS_MODEL_*` task slots
(`provider:model`), `JARVIS_DAILY_SPEND_CAP_INR` (default 200), the `JARVIS_UC*` use-case
toggles (all off in Phase 1).

## Troubleshooting
- **`/health` shows `ollama: {ok:false}`** — Ollama isn't running. `ollama serve`, then
  `ollama pull llama3.1:8b`. The server still runs; chat replies show a clear error.
- **`ModuleNotFoundError: fastapi`** — activate the venv and `pip install -r requirements.txt`.
- **`address already in use`** — another process holds the port. Pick another with
  `--port 8101`, or free 8100: `lsof -ti:8100 | xargs kill -9`.
- **`pytest` can't import `backend`** — run `pytest` from the project root (`~/Desktop/jarvis`).
- **On macOS, `--` sometimes autocorrects to an em-dash** in commands — retype flags if a
  command errors oddly.
```
