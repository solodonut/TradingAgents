#!/usr/bin/env bash
#
# batch.sh — start the TradingAgents WebUI backend (FastAPI :8000) and then run
# the batch-analysis TUI against it. If a backend is already listening on :8000
# it is reused (and left running); otherwise one is started here and shut down
# when the TUI exits. Backend logs go to a temp file so they don't fight the
# rich Live dashboard for the terminal.
#
# Usage:
#   ./batch.sh                     # start backend if needed, then run the TUI
#   ./batch.sh --api-url URL       # extra args are forwarded to `cli.main batch`
#
set -euo pipefail

API_PORT=8000
API_URL="http://localhost:${API_PORT}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_LOG="${TMPDIR:-/tmp}/tradingagents-batch-backend.log"
READY_TIMEOUT=120  # seconds; startup runs a model health check, so allow time

# --- resolve project Python --------------------------------------------------
# The project's .venv is required (requires-python >=3.10). The shell's
# `python3`/`uvicorn` on PATH may be an unrelated env (e.g. a Framework/conda
# Python with NumPy-1.x wheels that crash against this project's NumPy 2.x).
# Prefer .venv, never bare PATH.
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PY="$VIRTUAL_ENV/bin/python"
else
  echo "error: no project virtualenv found at .venv/. Create it and install dev deps:" >&2
  echo "       python3.10 -m venv .venv && .venv/bin/pip install -e \".[dev]\"" >&2
  exit 1
fi

# --- readiness probe ---------------------------------------------------------
api_up() { curl -fs -o /dev/null "${API_URL}/api/watchlist" 2>/dev/null; }

# --- child process tracking + cleanup ---------------------------------------
BACKEND_PID=""
cleanup() {
  if [ -n "$BACKEND_PID" ]; then
    echo
    echo "shutting down backend (PID $BACKEND_PID)…"
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# --- start backend (unless one is already serving) ---------------------------
if api_up; then
  echo "backend already up at ${API_URL} — reusing it (will leave it running)."
else
  if ! "$PY" -c "import uvicorn" >/dev/null 2>&1; then
    echo "error: uvicorn not installed in $PY. Run: $PY -m pip install -e \".[dev]\"" >&2
    exit 1
  fi
  echo "starting backend → ${API_URL}  (logs: ${BACKEND_LOG})"
  ( cd "$ROOT" && exec "$PY" -m uvicorn api.main:app --port "$API_PORT" ) \
    >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  printf 'waiting for backend to be ready'
  for _ in $(seq 1 "$READY_TIMEOUT"); do
    if api_up; then echo " — ready."; break; fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo
      echo "error: backend exited during startup. Last log lines:" >&2
      tail -n 20 "$BACKEND_LOG" >&2 || true
      exit 1
    fi
    printf '.'
    sleep 1
  done
  if ! api_up; then
    echo
    echo "error: backend not ready within ${READY_TIMEOUT}s. Last log lines:" >&2
    tail -n 20 "$BACKEND_LOG" >&2 || true
    exit 1
  fi
fi

# --- run the interactive batch TUI in the foreground -------------------------
echo "launching batch TUI…"
( cd "$ROOT" && exec "$PY" -m cli.main batch "$@" )
