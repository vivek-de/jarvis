#!/usr/bin/env bash
# scripts/start.sh — one-command launcher for JARVIS.
# Ensures Ollama is running (starts it if not), then starts the API on :8100.
# Usage:  bash scripts/start.sh      (or)  ./scripts/start.sh   after chmod +x
set -euo pipefail

# ── locate project root (this script lives in jarvis/scripts) ────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

HOST="${JARVIS_APP_HOST:-127.0.0.1}"
PORT="${JARVIS_APP_PORT:-8100}"
OLLAMA_URL="${JARVIS_OLLAMA_BASE_URL:-http://localhost:11434}"
MODEL="${JARVIS_OLLAMA_MODEL:-llama3.1:8b}"

echo "▶ JARVIS launcher"

# ── 1. virtualenv ────────────────────────────────────────────────────────────
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "  ⚠ no .venv found. Create it first:"
  echo "      python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# ── 2. ensure Ollama is up ───────────────────────────────────────────────────
ollama_up() { curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; }

if ollama_up; then
  echo "  ✓ Ollama already running"
else
  if ! command -v ollama >/dev/null 2>&1; then
    echo "  ✗ Ollama is not installed. Install from https://ollama.com then re-run."
    exit 1
  fi
  echo "  … starting 'ollama serve' in the background"
  # log to the project's logs/ dir; don't tie it to this shell
  mkdir -p logs
  nohup ollama serve >> logs/ollama.log 2>&1 &
  # wait up to ~20s for it to answer
  for i in $(seq 1 20); do
    if ollama_up; then echo "  ✓ Ollama is up"; break; fi
    sleep 1
    if [ "$i" -eq 20 ]; then echo "  ✗ Ollama did not come up in 20s — check logs/ollama.log"; exit 1; fi
  done
fi

# ── 3. check the model is present (warn only; don't auto-pull ~4.7GB) ────────
if command -v ollama >/dev/null 2>&1; then
  if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo "  ⚠ model '$MODEL' not found locally. Pull it once with:  ollama pull $MODEL"
    echo "    (the server will still start; chat replies will error until the model exists)"
  else
    echo "  ✓ model '$MODEL' present"
  fi
fi

# ── 3.5 free the port if a stale server is holding it ────────────────────────
# (Prevents an old uvicorn from serving stale code — the cause of the earlier
#  wrong-identity bug.)
if command -v lsof >/dev/null 2>&1 && lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  PIDS=$(lsof -ti tcp:"$PORT")
  echo "  ⚠ port $PORT already in use by PID(s): $PIDS — stopping the stale server"
  kill $PIDS 2>/dev/null || true
  sleep 1
  if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    kill -9 $(lsof -ti tcp:"$PORT") 2>/dev/null || true
    sleep 1
  fi
  if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    echo "  ✗ could not free port $PORT. Free it manually:  lsof -ti:$PORT | xargs kill -9"
    exit 1
  fi
  echo "  ✓ port $PORT freed"
fi

# ── 4. start the API (foreground; Ctrl-C to stop) ────────────────────────────
echo "  ▶ starting API at http://$HOST:$PORT   (Ctrl-C to stop)"
echo "    health:  curl -s http://$HOST:$PORT/health | python3 -m json.tool"
echo "    chat:    python3 scripts/chat.py"
exec uvicorn backend.main:app --host "$HOST" --port "$PORT"
