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

Easiest — one command (ensures Ollama is running, then starts the API on :8100):
```bash
bash scripts/start.sh
```

Or manually:
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

## Long-term memory (Phase 3, Postgres + pgvector)
Optional — JARVIS runs without it. To enable: set `JARVIS_DATABASE_URL` in `.env`
(e.g. `postgresql://<you>@localhost:5432/jarvis`) with `CREATE EXTENSION vector` done
on that DB, and `ollama pull nomic-embed-text`. The app auto-applies the memory
migration on startup; or run it standalone:
```bash
python3 scripts/migrate.py
```
Chat commands: `remember <X>`, `what do you know about <X>`, `forget <X>`,
`delete everything about <X>`. During normal chat, JARVIS retrieves the top-K
relevant memories into context and stores new durable facts per the Phase-2 policy.
SQLite still holds conversation sessions; Postgres holds long-term memory only.

## Skills (Phase 4)
Skills live in `skills/<name>/` as `skill.json` (name, description, triggers,
instructions, allowed_tools, permissions, io_schema) + `handler.py`
(`async def handle(ctx, query)`). On startup the registry loads them; each turn
JARVIS picks the best skill by trigger match and runs its handler, else falls back to
normal chat. `GET /skills` lists them. Built-in:
- **placement_prep** — `solved <p> topic:x difficulty:y`, `struggled <p>`, `what's due`,
  `deadline <label> on YYYY-MM-DD`, `my deadlines`, `progress`, `mock interview on <topic>`.
- **project_memory** — `update project <name>: <status>`, `where did I leave <name>`,
  `what's pending on <name>` (backed by Phase-3 memory).
- **trading_read** — read-only OptionIQ: portfolio NAV/P&L, momentum basket, Big Player,
  Kite status. Never places or suggests trades.

## Tools (Phase 5)
Deterministic, LLM-free capabilities the agent runs *before* the model and injects
the result into context. Each tool declares a permission tier — **READ** (auto),
**WRITE** (needs confirmation), **FINANCIAL** (always refused unless `confirm=True`;
JARVIS is read-only on money so it's never executed). Every call is audited to the
SQLite `audit_log` table and `logs/tools.log`. Built-in (all READ):
- **file_reader** — `read file <path>`; path-allowlisted to `data/` and `~/Downloads`,
  txt/md/json/csv only, 50KB cap.
- **calculator** — `calculate <expr>` / `what is <expr>`; AST-safe (no eval/exec),
  `+ - * / // % **` plus `sqrt/log/round`.
- **datetime** — `what time is it`, `is market open`, `days until YYYY-MM-DD`; IST clock
  and NSE session check (schedule only, not a trading signal).
- **web_search** — `search for X` / `look up X` / `google X`; DuckDuckGo, no API key,
  10s timeout, max 10 results, spam domains dropped.
- **web_fetch** — `fetch <url>` / `open url X` / `read page X`; httpx + BeautifulSoup,
  extracts text/title/links. SSRF-guarded (private/loopback IPs blocked, re-checked
  after redirects), 100KB cap, 15s timeout.

## MCP servers (Phase 6)
JARVIS can use tools from external [Model Context Protocol](https://modelcontextprotocol.io)
servers declared in `mcp/servers.json`. On startup each enabled server is launched
(stdio), its tools are discovered and registered as `<server>.<tool>` at the server's
permission tier. Startup is resilient: a server that fails to launch (missing `npx`,
bad package, SDK absent, or a start timeout) is logged, recorded with its error, and
skipped — it never takes JARVIS down. Check discovery with:
```bash
curl -s http://localhost:8100/mcp/status | python3 -m json.tool   # {server: {enabled, tool_count, error}}
curl -s http://localhost:8100/tools | python3 -m json.tool         # all registered tools
```
Full guide (adding a server, permission tiers, Brave Search example): `docs/ADDING_MCP_SERVERS.md`.

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
