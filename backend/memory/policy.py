"""
backend/memory/policy.py — "don't store everything" memory policy (Phase 2).
═══════════════════════════════════════════════════════════════════════════════
A transparent, rules-based classifier that decides whether a user utterance is
worth remembering, and if so under which category. This is v1 (deterministic,
stdlib-only, easy to test/audit). Phase 3 adds the durable store + semantic search
and may layer an LLM classifier on top of these rules.

The bias is toward NOT remembering. Secrets are never remembered.
Nothing here writes anything — Phase 3 owns storage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = {
    "preference", "decision", "deadline", "fact", "correction",
    "trading_discipline", "project",
}

KNOWN_PROJECTS = {"optioniq", "marketgpt", "jarvis", "aura", "devnexus", "roadsense-ai", "roadsense"}

# never remember if the text looks like it carries a secret
_SECRET = re.compile(
    r"(api[_\s-]?key|secret|password|passwd|token|access[_\s-]?token|"
    r"client[_\s-]?secret|bearer\s+[a-z0-9._-]{10,}|zerodha|kite\s+password)",
    re.I,
)
_EXPLICIT = re.compile(r"\b(remember|note this|keep in mind|make a note|don'?t forget)\b", re.I)
_CORRECTION = re.compile(r"\b(actually|correction|i meant|that'?s wrong|no,?\s|scratch that)\b", re.I)
_PREFERENCE = re.compile(r"\b(i prefer|prefer|always|never|don'?t|do not|call me|from now on|i like|i want you to)\b", re.I)
_DECISION = re.compile(r"\b(i decided|we decided|decided to|going with|i'?ll go with|chose|choosing|final decision)\b", re.I)
_DEADLINE = re.compile(r"\b(deadline|due|by (?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|\d)|"
                       r"\bOA\b|online assessment|interview|hackathon|submission|review on|"
                       r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", re.I)
_STATUS = re.compile(r"\b(done|finished|completed|shipped|built|pending|in progress|blocked|"
                     r"broke|fixed|deployed|working on|status)\b", re.I)
_QUESTION = re.compile(r"^\s*(what|why|how|when|who|where|which|can you|could you|is |are |do |does |should )", re.I)

IMPORTANCE = {
    "correction": 5, "decision": 4, "deadline": 4, "preference": 4,
    "project": 4, "trading_discipline": 3, "fact": 3,
}


@dataclass
class MemoryDecision:
    remember: bool
    category: str | None
    importance: int
    reason: str


def _project_in(text: str) -> str | None:
    low = text.lower()
    for p in KNOWN_PROJECTS:
        if re.search(rf"\b{re.escape(p)}\b", low):
            return "roadsense-ai" if p.startswith("roadsense") else p
    return None


def should_remember(text: str, source: str = "user") -> MemoryDecision:
    t = (text or "").strip()
    if not t:
        return MemoryDecision(False, None, 0, "empty")

    # 1. secrets — never
    if _SECRET.search(t):
        return MemoryDecision(False, None, 0, "looks like a secret/credential — never stored")

    # 2. journal replies are trading discipline by source
    if source == "journal":
        return MemoryDecision(True, "trading_discipline", IMPORTANCE["trading_discipline"], "journal reflection")

    # 3. explicit user request wins
    if _EXPLICIT.search(t):
        cat = ("correction" if _CORRECTION.search(t) else
               "preference" if _PREFERENCE.search(t) else
               "decision" if _DECISION.search(t) else
               "deadline" if _DEADLINE.search(t) else
               ("project" if _project_in(t) else "fact"))
        return MemoryDecision(True, cat, IMPORTANCE.get(cat, 3), "explicit remember request")

    # 4. plain questions are not memories
    if _QUESTION.search(t) and not _CORRECTION.search(t):
        return MemoryDecision(False, None, 0, "a question, not a durable fact")

    # 5. content-typed durable statements
    if _CORRECTION.search(t):
        return MemoryDecision(True, "correction", IMPORTANCE["correction"], "correction supersedes prior memory")
    if _DEADLINE.search(t):
        return MemoryDecision(True, "deadline", IMPORTANCE["deadline"], "date/deadline stated")
    if _PREFERENCE.search(t):
        return MemoryDecision(True, "preference", IMPORTANCE["preference"], "stated preference")
    if _DECISION.search(t):
        return MemoryDecision(True, "decision", IMPORTANCE["decision"], "stated decision")
    proj = _project_in(t)
    if proj and _STATUS.search(t):
        return MemoryDecision(True, "project", IMPORTANCE["project"], f"project status for {proj}")

    # 6. default: don't remember
    return MemoryDecision(False, None, 0, "transient — not worth remembering")
