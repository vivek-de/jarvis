#!/usr/bin/env python3
"""
scripts/chat.py — simple terminal chat client for JARVIS (Phase 1).
Talks to a running server (uvicorn backend.main:app) via POST /chat, keeping the
session id across turns so history works. Shows the execution trace per reply.

Usage:
    python3 scripts/chat.py                 # uses JARVIS_APP_HOST/PORT (default 127.0.0.1:8100)
    JARVIS_APP_PORT=8100 python3 scripts/chat.py
Type 'exit' or Ctrl-D to quit.
"""
from __future__ import annotations

import os
import sys

import httpx

HOST = os.environ.get("JARVIS_APP_HOST", "127.0.0.1")
PORT = os.environ.get("JARVIS_APP_PORT", "8100")
BASE = f"http://{HOST}:{PORT}"


def main() -> int:
    # confirm server is up
    try:
        h = httpx.get(f"{BASE}/health", timeout=5).json()
    except Exception as e:
        print(f"✗ Cannot reach JARVIS at {BASE} ({e}).")
        print("  Start it first:  uvicorn backend.main:app --host 127.0.0.1 --port 8100")
        return 1

    ollama = h.get("ollama", {})
    print(f"JARVIS {h.get('app',{}).get('version','?')} — status: {h.get('status')} | "
          f"ollama: {'up' if ollama.get('ok') else 'DOWN'} | db: {'ok' if h.get('db',{}).get('ok') else 'fail'}")
    if not ollama.get("ok"):
        print("  ⚠ Ollama is not reachable — chat replies will show a clear error until it's running.")
    print("Type your message (or 'exit').\n")

    session_id: str | None = None
    while True:
        try:
            msg = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not msg:
            continue
        if msg.lower() in ("exit", "quit"):
            return 0
        try:
            r = httpx.post(f"{BASE}/chat",
                           json={"message": msg, "session_id": session_id, "channel": "cli"},
                           timeout=180)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  ✗ request failed: {e}\n")
            continue
        session_id = data["session_id"]
        t = data["trace"]
        print(f"jarvis › {data['reply']}")
        note = f" | fallback: {t['notice']}" if t.get("is_fallback") else ""
        print(f"        ⤷ {t['provider']}:{t['model']} · {t['latency_ms']}ms · "
              f"{t['completion_tokens']} tok · ₹{t['cost_inr']}{note}\n")


if __name__ == "__main__":
    sys.exit(main())
