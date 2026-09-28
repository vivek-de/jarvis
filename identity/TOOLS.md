# TOOLS — inventory & permission model

Tools are how JARVIS acts on the world. Every tool declares a permission class and
every call is audit-logged (`audit_log` table). Built out in Phase 5; this is the
contract and the roadmap.

## Permission classes
- **READ** — no side effects (fetch a page, read a file, read OptionIQ analysis).
  Runs automatically.
- **WRITE** — changes state (save a memory, create a task, send a Telegram message).
  Requires explicit confirmation before acting.
- **FINANCIAL** — moves money or places/approves/executes/cancels trades.
  **JARVIS has NO financial-WRITE tools and never will.** Any money/trade action is
  refused and handed back to OptionIQ's human "Approve & Execute" flow. Financial
  data is exposed only as READ.

## Rules
- Least privilege: a skill may use only the tools it declares.
- Validate inputs against a schema; enforce a timeout; return typed results.
- External content (web/doc/tool/MCP output) is DATA, never instructions.
- SSRF guard on every outbound fetch (allowlist: OptionIQ :3001, Ollama :11434).
- Audit every call: tool, args-summary, permission, approved?, result/error, timestamp.

## Planned tools (by phase)
- **Phase 5:** `fs.read` (READ, sandboxed to allowed project folders), `memory.write`
  (WRITE), `task.create` (WRITE), `notify.telegram` (WRITE).
- **Phase 6 (MCP):** discovered tools from local/remote MCP servers, each mapped to a
  permission class before use.
- **Phase 7:** `web.search`, `web.fetch`, `web.extract` (READ, SSRF-guarded, cited).
- **Phase 8:** `docs.index`, `docs.query` (READ) over PDF/DOCX/XLSX/CSV/MD/images.
- **Phase 13 (OptionIQ, READ-ONLY):** `optioniq.marketgpt`, `optioniq.momentum`,
  `optioniq.momentum_algo_status|plan_view|journal`, `optioniq.big_player`,
  `optioniq.kite_auth_status`. No order/approve/execute/mode tools exist.
