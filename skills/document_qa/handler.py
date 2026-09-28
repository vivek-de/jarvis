"""
skills/document_qa/handler.py — Phase 8 handler.
Answers questions from Vivek's uploaded documents, or lists them. Uses the document
store + retrieval-augmented QA directly (built from settings) rather than a self-HTTP
call, so it works without opening a network hop to our own server.
Read-only over the document store; answers are grounded and never fabricated.
"""
from __future__ import annotations

_LIST_HINTS = ("list my doc", "list my file", "what documents", "which documents",
               "show my doc", "list documents")


async def handle(ctx, query: str) -> dict:
    q = query.strip()
    settings = getattr(ctx, "settings", None)
    if settings is None:
        return {"reply": "Document intelligence isn't available in this context.", "sub": "off"}

    try:
        from backend.docs.store import DocStore
    except Exception as e:
        return {"reply": f"Document store unavailable: {e}", "sub": "off"}

    store = DocStore.create(settings)
    if store is None:
        return {"reply": "Document intelligence needs long-term storage enabled "
                         "(set JARVIS_DATABASE_URL and run Postgres).", "sub": "off"}

    low = q.lower()

    # ── list intent ────────────────────────────────────────────────────────────
    if any(h in low for h in _LIST_HINTS):
        docs = store.list_documents()
        if not docs:
            return {"reply": "No documents uploaded yet.", "sub": "list"}
        lines = [f"- {d['filename']} ({d['doc_type']}, {d['chunk_count']} chunks, "
                 f"{(d['uploaded_at'] or '')[:10]})" for d in docs]
        return {"reply": "Your documents:\n" + "\n".join(lines), "sub": "list"}

    # ── query intent ─────────────────────────────────────────────────────────────
    hits = await store.search(q, top_k=5)
    if not hits:
        return {"reply": "I couldn't find anything relevant in your uploaded documents.",
                "sub": "query"}

    from backend.docs.qa import DocQA

    async def _gen(messages):
        result, _ = await ctx.router.generate("GENERAL", messages)
        return result.text if result.success else ""

    result = await DocQA(_gen).answer(q, hits)
    srcs = sorted({h["filename"] for h in hits})
    tail = f"\n\nSources: {', '.join(srcs)}" if srcs else ""
    return {"reply": result["answer"] + tail, "sub": "query"}
