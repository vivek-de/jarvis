# JARVIS — Security Model

Security is first-class from Phase 1. This document is updated every phase.

## Secrets
- All secrets live in `.env` (git-ignored). `.env.example` is the committed template.
- `.gitignore` covers `.env`, `data/`, `logs/`, and all `*.db`/`*.sqlite` files.
- Secrets are never returned to the frontend, never written to logs, never committed.
  The structured logger only serializes explicit `extra={}` fields — no request bodies
  or API keys are logged.

## Prompt-injection defense (data ≠ instructions)
- The agent's system prompt states that content from tools, web pages, and documents
  is **data, never instructions**. As tool/web/MCP layers arrive (Phases 5–8), each
  wraps external content as data and never lets it change the agent's directives.

## SSRF defense (`backend/security/ssrf.py`, enforced from Phase 7)
- The fetch/browse layer must call `ssrf.check_url(url, allowlist)` before any request.
- Requests to localhost / private / loopback / link-local IPs are **blocked** unless the
  exact `host:port` is on the allowlist. Defaults allow only OptionIQ `:3001` and
  Ollama `:11434`. Public web hosts are allowed.

## Rate limiting (`backend/security/ratelimit.py`)
- Per-client fixed-window limiter (default 60 req/min), applied as middleware; `/health`
  is exempt. Returns HTTP 429 when exceeded. Redis-backed limiting can replace it later.

## Audit logging
- Every LLM call is recorded in `llm_calls` (provider, model, tokens, latency, cost,
  success/failure). The `audit_log` table is defined now; from Phase 5 every tool call
  (READ / WRITE / FINANCIAL) is written there with its permission and approval state.

## Spend cap
- Cloud calls are refused once the day's cloud spend reaches the configured ₹ cap
  (default ₹200/day, IST calendar day); the router falls back to local Ollama with a
  visible notice. Local inference is free and never capped.

## Trading safety (all phases)
- JARVIS is **read-only** with respect to trading. It may read OptionIQ analysis,
  holdings, journals, and plans, but it **never** places, approves, or executes orders,
  and never toggles PAPER/LIVE. Execution stays inside OptionIQ's own risk engine and
  its human "Approve & Execute" flow. Zerodha credentials are never stored in JARVIS.

## Network posture
- Binds to `127.0.0.1` by default (not exposed on the network).
- Cloud providers are key-gated and OFF by default; the system runs fully on local Ollama.

## Reporting
- This is a single-user personal project. If you find an issue, fix-forward and note it
  in `docs/` and this file.
