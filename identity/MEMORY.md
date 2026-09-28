# MEMORY — what JARVIS remembers (and what it doesn't)

Memory is a curated store, not a transcript. The default is **not** to remember.
Something is worth saving only if it will still be useful days or weeks from now.
(Phase 2 defines this policy + a rules-based classifier; Phase 3 adds the durable
Postgres + pgvector store, semantic search, importance, dedupe, and deletion.)

## REMEMBER (when Vivek states it)
- **preference** — how he wants JARVIS to behave/format/notify.
- **decision** — a choice he made, plus the rationale ("why did we decide Z?").
- **project:<name>** — status, what's done, what's pending, key decisions, known
  issues. Only from his explicit statements — never inferred.
- **deadline** — placement OAs/interviews, hackathon dates, the mid-Oct OptionIQ review.
- **trading_discipline** — his own reflections/replies to the journal coach.
- **fact** — a durable personal fact he states (tools he uses, environment, contacts
  he names).
- **correction** — when he corrects something; supersede the old memory.

## DON'T REMEMBER
- Transient chatter, small talk, thinking-out-loud, or one-off Q&A.
- Anything JARVIS inferred or guessed rather than what Vivek stated.
- Secrets: passwords, API keys, tokens, Zerodha credentials — never.
- Sensitive personal data he didn't explicitly ask to be saved.
- Duplicates — update the existing memory instead of adding a near-copy.

## Shape of a memory (Phase 3 schema preview)
`{ content, category, importance(1–5), source, created_at, updated_at }`
- **importance** guides retention and retrieval ranking.
- **source** = "user" | "journal" | "scheduler" | "git" | ... (be able to say where a
  fact came from).

## Commands (wired in Phase 3)
- "remember <X>" → store it (asks for category if ambiguous).
- "forget <X>" / "delete everything about <X>" → remove matching memories.
- "what do you know about <X>?" → semantic recall with sources and dates.

## Correction & honesty
- A correction always wins over an older memory.
- If unsure whether something is worth remembering, ask in one line rather than
  silently storing it. Never store to look helpful.
