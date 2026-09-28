"""
backend/memory/commands.py — parse explicit memory commands from chat (Phase 3).
Pure/stdlib, testable. Recognizes:
  remember X                      → store X
  forget X                        → soft-delete memories about X
  delete everything about X       → hard-delete memories about X
  what do you know about X        → recall memories about X
Anything else → None (normal chat).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_REMEMBER = re.compile(r"^\s*remember(?:\s+that|\s+this)?\s*[:,-]?\s+(.+)$", re.I | re.S)
_RECALL = re.compile(r"^\s*(?:what do you know about|what do you remember about|recall)\s+(.+?)\s*\??\s*$", re.I | re.S)
_DELETE_ALL = re.compile(r"^\s*(?:delete everything about|delete all memories about|wipe everything about)\s+(.+?)\s*\.?\s*$", re.I | re.S)
_FORGET = re.compile(r"^\s*(?:forget(?:\s+about)?)\s+(.+?)\s*\.?\s*$", re.I | re.S)


@dataclass
class Command:
    kind: str        # "remember" | "recall" | "forget" | "delete"
    arg: str


def parse_command(text: str) -> Command | None:
    t = (text or "").strip()
    if not t:
        return None
    # order matters: "delete everything about" before generic "forget"
    m = _REMEMBER.match(t)
    if m:
        return Command("remember", m.group(1).strip())
    m = _RECALL.match(t)
    if m:
        return Command("recall", m.group(1).strip())
    m = _DELETE_ALL.match(t)
    if m:
        return Command("delete", m.group(1).strip())
    m = _FORGET.match(t)
    if m:
        return Command("forget", m.group(1).strip())
    return None
