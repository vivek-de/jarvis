# JARVIS — Architecture (Phase 1)

## Runtime decision: thin custom FastAPI loop (NOT Hermes Agent)

**Chosen: a thin custom tool-use loop on FastAPI.** Reasoning for a single-user Mac
assistant with the requirements in the brief:

| Criterion | Custom FastAPI loop | Hermes Agent (Nous Research) |
|---|---|---|
| Ollama support | First-class — we call `/api/chat` directly | Works, but through the framework's own model layer |
| Debuggability | Every step is our code + a JSON exec-trace | Framework internals to reason about when things break |
| Permissions/audit | We own READ/WRITE/FINANCIAL gates + audit log exactly as specified | Must bend the framework's abstractions to fit |
| Spend cap / router | Native — we control provider selection per call | Extra layer to intercept |
| Channel-independence | Core is transport-agnostic; Web/Telegram/voice are thin adapters | Framework assumes its own I/O shape |
| Fit with OptionIQ read-only risk rules | Trivial — we simply never expose write tools | Same, but with more moving parts |
| Dependency weight | fastapi + httpx + pydantic only | A heavier agent framework + its deps |

Priorities are **WORKING > COMPLEX, SECURE > FAST, MODULAR > MONOLITHIC,
VERIFIABLE > ASSUMED.** A framework adds opacity and coupling that work against all
four. The phases (skills, tools, MCP, memory, automation) each bolt onto a small,
explicit loop far more cleanly than they fit inside a general agent runtime. If a real
need for a heavier framework appears later, the provider/agent seam makes it swappable.

## Component map (Phase 1)

```
             ┌──────────── FastAPI (backend/main.py) ────────────┐
  client ──▶ │  RateLimitMiddleware ─▶ routes(/health,/chat,…)   │
  (CLI/web)  │            │                                      │
             │            ▼                                      │
             │        Agent (agent/runtime.py)                   │
             │        · session history (SQLite)                 │
             │        · exec trace (why this model/why fallback) │
             │            │                                      │
             │            ▼                                      │
             │     ModelRouter (models/router.py)                │
             │     · task slots (GENERAL/FAST/CODING/…)          │
             │     · routing_core.route_decision (pure)          │
             │     · SpendTracker (₹/day cap)                    │
             │        │                │                         │
             │        ▼                ▼                         │
             │  OllamaProvider   Cloud providers (STUB, gated)   │
             └───────────────────────────────────────────────────┘
   Config (pydantic-settings) · JSON logging · SQLite + migrations
```

## Data flow: one `/chat` turn
1. Resolve/create conversation, store the user message (SQLite).
2. Build `system + bounded history` (≤20 msgs; real memory arrives Phase 3).
3. `ModelRouter.resolve(slot)` → decide provider (key-gate + spend-cap fallback).
4. Provider `.generate()` → `ModelResult` (never raises for expected failures).
5. Cost accounting (cloud only), persist assistant reply on success, log the LLM call.
6. Return `{session_id, reply, trace}` — the trace answers "why did JARVIS do this?".

## What's deliberately deferred (labeled stubs / placeholders)
- Cloud providers: key-gated **stubs** (price tables real for the cap; `generate()` not wired).
- `backend/{memory,tools,skills,automation,integrations,trading}`: placeholder packages
  for their phases. `security/ssrf.py` is implemented now but only enforced from Phase 7.

## Storage
- SQLite (`data/jarvis.db`), schema via versioned SQL in `backend/database/migrations`.
  Phase 3 re-homes long-term memory to Postgres + pgvector (Alembic from then on).
