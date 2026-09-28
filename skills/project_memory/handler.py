"""
skills/project_memory/handler.py — UC5 handler.
Records project status/decisions (only when Vivek states them) and answers project
questions strictly from stored memory. Backed by Phase-3 Postgres memory.
"""
from __future__ import annotations

import re

_UPDATE = re.compile(r"^\s*(?:update project|note on|log)\s+(.+?)\s*[:\-]\s*(.+)$", re.I | re.S)


async def handle(ctx, query: str) -> dict:
    q = query.strip()
    mem = ctx.memory
    if mem is None or not getattr(mem, "enabled", False):
        return {"reply": "Project memory needs long-term memory enabled (JARVIS_DATABASE_URL).", "sub": "off"}

    # ── explicit update: "update project OptionIQ: momentum goes live mid-Oct" ─
    m = _UPDATE.match(q)
    if m:
        project, statement = m.group(1).strip(), m.group(2).strip()
        content = f"[{project}] {statement}"
        res = await mem.remember(content, category="project", source="user")
        if not res.get("ok"):
            return {"reply": f"Couldn't save that — {res.get('error')}.", "sub": "update"}
        verb = "Updated" if res.get("action") == "updated" else "Saved"
        return {"reply": f"{verb} project note for {project}.", "sub": "update"}

    # ── question: recall relevant project memories ────────────────────────────
    hits = await mem.recall(q, top_k=6, min_similarity=0.3)
    if not hits:
        return {"reply": "I don't have that on file. Tell me and I'll remember: "
                         "\"update project <name>: <what happened>\".", "sub": "recall"}
    lines = [f"- {h['content']}  [{int(h['similarity']*100)}% match]" for h in hits]
    return {"reply": "From project memory:\n" + "\n".join(lines), "sub": "recall"}
