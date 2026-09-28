"""
skills/placement_prep/handler.py — UC4 handler.
Sub-intents: log a DSA problem, mark solved/struggled (spaced repetition), list what's
due to review, add/list deadlines, show progress, or run a mock interview (LLM).
Structured data → SQLite (ctx.db); mock interview → ctx.router. Plain-text replies.
"""
from __future__ import annotations

import re

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TOPIC = re.compile(r"topic\s*[:=]\s*([a-z0-9 &/+-]+)", re.I)
_DIFF = re.compile(r"difficulty\s*[:=]\s*(easy|medium|hard)", re.I)


def _kind(text: str) -> str:
    t = text.lower()
    if "oa" in t or "assessment" in t:
        return "OA"
    if "interview" in t:
        return "interview"
    return "other"


async def handle(ctx, query: str) -> dict:
    q = query.strip()
    low = q.lower()
    db = ctx.db

    # ── deadlines ─────────────────────────────────────────────────────────────
    if "deadline" in low:
        m = _DATE.search(q)
        if m and any(w in low for w in ("add", "set", "new", "on", "deadline")):
            date = m.group(1)
            label = re.sub(r"(add|set|new)?\s*deadline\s*[:-]?", "", q, flags=re.I)
            label = _DATE.sub("", label).replace(" on ", " ").strip(" :-,") or "deadline"
            db.add_deadline(label, date, _kind(low))
            return {"reply": f"Deadline noted: {label} — {date} ({_kind(low)}).", "sub": "deadline_add"}
        dls = db.list_deadlines(upcoming_only=True)
        if not dls:
            return {"reply": "No upcoming deadlines on file. Add one: \"deadline Amazon OA on 2026-10-05\".", "sub": "deadline_list"}
        lines = [f"- {d['due_date']}  {d['label']} ({d['kind']})" for d in dls]
        return {"reply": "Upcoming deadlines:\n" + "\n".join(lines), "sub": "deadline_list"}

    # ── review queue (spaced repetition) ─────────────────────────────────────
    if any(k in low for k in ("what's due", "whats due", "due today", "to review", "what should i review", "revise")):
        due = db.due_dsa()
        if not due:
            return {"reply": "Nothing due for review today. 👍", "sub": "due"}
        lines = [f"- {d['name']} ({d['topic'] or '?'}, {d['difficulty'] or '?'}) — stage {d['review_stage']}" for d in due]
        return {"reply": f"Due to review ({len(due)}):\n" + "\n".join(lines), "sub": "due"}

    # ── progress ──────────────────────────────────────────────────────────────
    if "progress" in low or "stats" in low:
        s = db.dsa_stats()
        topics = ", ".join(f"{k}:{v}" for k, v in list(s["by_topic"].items())[:8]) or "none yet"
        weak = ", ".join(s["weak_topics"]) or "none flagged"
        return {"reply": f"DSA progress: {s['total']} logged.\nBy topic: {topics}\nWeak: {weak}", "sub": "progress"}

    # ── mark struggled / solved (review or first log) ────────────────────────
    m = re.match(r"^\s*struggled(?:\s+with|\s+on)?\s+(.+)$", q, re.I)
    if m:
        name = _clean_name(m.group(1))
        r = db.review_dsa(name, "struggled")
        if not r:
            db.log_dsa(name, _topic(q), _diff(q), "struggled")
            return {"reply": f"Logged \"{name}\" as struggled — review tomorrow.", "sub": "log"}
        return {"reply": f"Marked \"{name}\" struggled — reset to review tomorrow.", "sub": "review"}

    m = re.match(r"^\s*solved\s+(.+)$", q, re.I)
    if m:
        name = _clean_name(m.group(1))
        r = db.review_dsa(name, "solved")
        if not r:
            db.log_dsa(name, _topic(q), _diff(q), "solved")
            return {"reply": f"Logged \"{name}\" as solved — first review tomorrow.", "sub": "log"}
        if r["graduated"]:
            return {"reply": f"\"{name}\" reviewed & graduated from the schedule. 🎓", "sub": "review"}
        return {"reply": f"\"{name}\" reviewed — next review {r['next_review']} (stage {r['stage']}).", "sub": "review"}

    m = re.match(r"^\s*log(?:\s+dsa)?\s+(.+)$", q, re.I)
    if m:
        name = _clean_name(m.group(1))
        res = db.log_dsa(name, _topic(q), _diff(q), "solved")
        return {"reply": f"Logged \"{name}\" — first review {res['next_review']}.", "sub": "log"}

    # ── mock interview (LLM) ─────────────────────────────────────────────────
    if any(k in low for k in ("mock", "quiz", "ask me", "interview question", "interview")):
        if ctx.router is None:
            return {"reply": "Mock interview needs the model router (unavailable).", "sub": "mock"}
        sysmsg = ctx.extras.get("skill_instructions", "")
        result, _ = await ctx.router.generate("CODING", [
            {"role": "system", "content": sysmsg},
            {"role": "user", "content": q},
        ])
        text = result.text if result.success else f"(model error: {result.error})"
        return {"reply": text, "sub": "mock"}

    # ── fallback: treat as placement help via the coach LLM ──────────────────
    if ctx.router is not None:
        sysmsg = ctx.extras.get("skill_instructions", "")
        result, _ = await ctx.router.generate("GENERAL", [
            {"role": "system", "content": sysmsg},
            {"role": "user", "content": q},
        ])
        if result.success:
            return {"reply": result.text, "sub": "coach"}
    return {"reply": "Try: \"solved two-sum topic:arrays difficulty:easy\", \"what's due\", "
                     "\"deadline Amazon OA on 2026-10-05\", or \"mock interview on graphs\".", "sub": "help"}


def _clean_name(s: str) -> str:
    s = _TOPIC.sub("", s); s = _DIFF.sub("", s)
    return s.strip(" .:-,")


def _topic(s: str):
    m = _TOPIC.search(s)
    return m.group(1).strip() if m else None


def _diff(s: str):
    m = _DIFF.search(s)
    return m.group(1).lower() if m else None
